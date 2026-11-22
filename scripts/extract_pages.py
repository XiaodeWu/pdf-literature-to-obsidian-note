#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PDF → 逐页结构化切片（带页码溯源），供 Obsidian 笔记生成使用。

设计要点（对应 skill 的三条原则）：
  逐页    : pymupdf4llm.to_markdown(page_chunks=True)，一页一个 chunk，天然避免长文档上下文溢出
  溯源    : 每页落盘 JSON，带 metadata.page_number（PDF 页码）与 toc_items（章节路径）
  断点续传: 已存在的页默认跳过（--force 强制重跑），长文档中途失败不用从头来

输出：
  <out>/pages/pNNNN.json   每页切片
  <out>/index.jsonl        每页一行摘要（页码 / toc / 字符数 / 疑似表格 / 疑似图表）
  <out>/manifest.json      文档级元信息 + 页码偏移探测结果
  <out>/values.txt         数值判据扫描结果（page + 条款号 + 上下文）

用法：
  python extract_pages.py <pdf> [--out DIR] [--start N] [--end N] [--force]
  python extract_pages.py <pdf> --scan-only          # 只扫描，不落盘全文（快）
"""
import argparse
import json
import os
import re
import sys
import time

# ---- 数值判据扫描规则：按需扩充 ----
UNIT_PATTERNS = [
    r"\d+(?:\.\d+)?\s?(?:m/s|ft/s)",            # 流速
    r"\d+(?:\.\d+)?\s?mJ",                       # 点火能
    r"\d+(?:\.\d+)?\s?(?:megohm|MΩ|M ohm)",      # 接地电阻
    r"\d+(?:\.\d+)?\s?(?:ohm|Ω)(?:\s|$)",
    r"resistivity",                              # 电阻率
    r"\d+(?:\.\d+)?\s?(?:psig|kPag|barg|bar|kPa|MPa)(?:\s|[.,;)])",
    r"\d+(?:\.\d+)?\s?(?:in\.?2|mm2|cm2)\b",     # 面积
    r"\d+(?:\.\d+)?\s?%",                        # 百分比
    r"\b(?:MIE|LFL|UFL|MEC|MAWP|MDMT)\b",        # 关键缩写（必须加词边界，否则 mechanical→MEC）
]
CLAUSE_RE = re.compile(r"\b(\d{1,2}(?:\.\d{1,2}){1,5})\b")


def detect_page_offset(chunks):
    """探测 PDF 页码 vs 印刷页码的偏移。
    思路：页文本首/尾部常出现印刷页码孤立成行，取众数与 PDF 页码之差。"""
    diffs = {}
    for c in chunks:
        pn = c["metadata"]["page_number"]
        txt = c.get("text", "")
        # 孤立成行的 1-3 位数字（页眉页脚）
        for m in re.finditer(r"(?m)^\s*\*{0,2}(\d{1,3})\*{0,2}\s*$", txt):
            v = int(m.group(1))
            if 0 < v < 1000:
                d = pn - v
                diffs[d] = diffs.get(d, 0) + 1
    if not diffs:
        return None, 0
    best = max(diffs.items(), key=lambda kv: kv[1])
    return best[0], best[1]


def build_toc_index(chunks):
    """把所有 chunk 的 toc_items 汇总成 {page: [title,...]}，用于给每页标注章节路径。"""
    idx = {}
    for c in chunks:
        pn = c["metadata"]["page_number"]
        for item in c.get("toc_items") or []:
            # item 形如 [level, title, page] 或 dict
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                idx.setdefault(int(item[2]) if len(item) > 2 else pn, []).append(item[1])
            elif isinstance(item, dict):
                idx.setdefault(int(item.get("page", pn)), []).append(item.get("title", ""))
    return idx


def toc_path_for(page, toc_idx):
    """返回 <=page 的最后一个 toc 标题作为该页所属章节（简单近似，够用）。"""
    best_p, best_t = None, None
    for p in sorted(toc_idx):
        if p <= page and (best_p is None or p > best_p):
            best_p, best_t = p, toc_idx[p]
    return best_t[-1] if best_t else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--out", default=os.path.join(os.getcwd(), "extract"))
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=0, help="0 = 到末页")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--scan-only", action="store_true", help="不落盘每页全文，只出 index/values")
    a = ap.parse_args()

    import pymupdf4llm  # 依赖：pip install pymupdf4llm

    t0 = time.time()
    doc_pages = None
    try:
        import pymupdf
        with pymupdf.open(a.pdf) as d:
            doc_pages = d.page_count
    except Exception:
        pass
    if doc_pages is None:
        doc_pages = a.end or 9999

    end = a.end or doc_pages
    end = min(end, doc_pages)
    # ⚠️ pymupdf4llm 的 pages 参数是 **0-based 页索引**；返回的 metadata.page_number 是 1-based。
    # 例：传 pages=[58] → page_number == 59。越界会抛 ValueError。
    page_list = list(range(a.start - 1, end))
    print(f"[i] {os.path.basename(a.pdf)[:60]}  pages {a.start}-{end} (1-based) / total {doc_pages}")

    chunks = pymupdf4llm.to_markdown(a.pdf, pages=page_list, page_chunks=True)
    print(f"[i] extracted {len(chunks)} chunks in {time.time()-t0:.1f}s")

    os.makedirs(os.path.join(a.out, "pages"), exist_ok=True)
    toc_idx = build_toc_index(chunks)
    offset, hits = detect_page_offset(chunks)

    index_lines, value_lines = [], []
    for c in chunks:
        pn = c["metadata"]["page_number"]
        text = c.get("text", "") or ""
        path = toc_path_for(pn, toc_idx)
        ntable = text.count("\n|")
        has_fig = bool(re.search(r"(?i)\b(figure|fig\.)\s*\d", text))

        rec = {
            "page_number": pn,          # PDF 页码（溯源主键）
            "printed_page": (pn - offset) if offset is not None else None,
            "toc_path": path,
            "toc_items": c.get("toc_items") or [],
            "char_count": len(text),
            "pipe_rows": ntable,
            "has_figure_ref": has_fig,
            "text": text,
        }
        if not a.scan_only:
            fp = os.path.join(a.out, "pages", f"p{pn:04d}.json")
            if a.force or not os.path.exists(fp):
                with open(fp, "w", encoding="utf-8") as f:
                    json.dump(rec, f, ensure_ascii=False, indent=1)

        index_lines.append(json.dumps({
            "page": pn, "printed": rec["printed_page"], "toc": path,
            "chars": len(text), "piperows": ntable, "figure": has_fig,
        }, ensure_ascii=False))

        # 数值判据扫描（跳过前置页：目录点线、版权声明会大量误报）
        is_front = rec["printed_page"] is None or rec["printed_page"] < 1
        if is_front:
            continue
        for pat in UNIT_PATTERNS:
            for m in re.finditer(pat, text, re.I):
                s = max(0, m.start() - 180)
                ctx = re.sub(r"\s+", " ", text[s:m.end() + 180]).strip()
                cm = CLAUSE_RE.search(ctx)
                value_lines.append(
                    f"[p{pn}{('/'+str(rec['printed_page'])) if rec['printed_page'] else ''}]"
                    f" [{cm.group(1) if cm else '—'}] {m.group(0)!r} :: {ctx}"
                )

    with open(os.path.join(a.out, "index.jsonl"), "w", encoding="utf-8") as f:
        f.write("\n".join(index_lines))
    with open(os.path.join(a.out, "values.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(dict.fromkeys(value_lines)))  # 去重保序
    with open(os.path.join(a.out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({
            "source": a.pdf,
            "page_count": doc_pages,
            "extracted": [a.start, end],
            "printed_page_offset": offset,   # PDF页码 = 印刷页码 + offset
            "offset_confidence_hits": hits,
            "toc_entries": len(toc_idx),
            "elapsed_s": round(time.time() - t0, 1),
        }, f, ensure_ascii=False, indent=1)

    print(f"[✓] out={a.out}  offset={offset} (hits={hits})  "
          f"values={len(set(value_lines))}  total {time.time()-t0:.1f}s")


if __name__ == "__main__":
    sys.exit(main())

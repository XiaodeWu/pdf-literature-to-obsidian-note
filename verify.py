# -*- coding: utf-8 -*-
"""环境自检：依赖 + 端到端迷你测试（生成一份 3 页测试 PDF 全流程跑一遍）。

用法：
    python verify.py

退出码 0 = 全部通过；1 = 有 FAIL。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import pathlib

# Windows 下输出被重定向/管道捕获时强制 UTF-8，避免中文变乱码
for _s in (sys.stdout, sys.stderr):
    try:
        if not _s.isatty():
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = pathlib.Path(__file__).resolve().parent
EXTRACTOR = HERE / "scripts" / "extract_pages.py"
results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    flag = "PASS" if ok else "FAIL"
    print(f"[{flag}] {name}" + (f" — {detail}" if detail else ""))


def step1_deps():
    print("=" * 62)
    print("1/4  检查依赖")
    print("=" * 62)
    mods = [
        ("pymupdf4llm", "pymupdf4llm"),
        ("pymupdf", "pymupdf"),
        ("pdfplumber", "pdfplumber"),
        ("pypdfium2", "pypdfium2"),
    ]
    version = None
    for label, mod in mods:
        try:
            m = __import__(mod)
            v = getattr(m, "__version__", "?")
            if label == "pymupdf4llm":
                version = v
            print(f"       {label:12s} {v}")
        except ImportError as e:
            check(f"依赖 {label}", False, f"未安装（{e}）")
            return False
    check("依赖齐全", True, f"pymupdf4llm {version}")

    try:
        import pydantic
        print(f"       pydantic     {pydantic.VERSION}  (可选，已装)")
    except ImportError:
        print("       pydantic     —  (可选，未装，仅影响 LLM API 结构化输出)")
    return True


def make_test_pdf(path):
    """生成 3 页测试 PDF：封面 / 正文+标题 / 表格+数值判据。"""
    import pymupdf

    doc = pymupdf.open()

    def page(n, footer=None):
        p = doc.new_page(width=595, height=842)
        if footer:
            p.insert_text((285, 800), footer, fontsize=10, fontname="helv")
        return p

    # 封面（无印刷页码 → 测 offset 探测跳过前置页）
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((70, 120), "TEST STANDARD ON EXPLOSION PREVENTION",
                   fontsize=22, fontname="hebo")
    p1.insert_text((70, 160), "2019 Edition  -  generated for verify.py",
                   fontsize=11, fontname="helv")

    # 正文页，印刷页码 1
    p2 = page(2, "1")
    p2.insert_text((70, 100), "Chapter 1  Administration", fontsize=18, fontname="hebo")
    p2.insert_text((70, 140), "1.1 Scope. This document is a synthetic sample used",
                   fontsize=11, fontname="helv")
    p2.insert_text((70, 158), "only to validate the extraction pipeline.", fontsize=11,
                   fontname="helv")
    p2.insert_text((70, 196), "1.2 Purpose. To verify page-level traceability.",
                   fontsize=12, fontname="hebo")
    p2.insert_text((70, 230), "The design velocity shall not exceed 0.3 m/s in the",
                   fontsize=11, fontname="helv")
    p2.insert_text((70, 248), "duct under normal operating conditions.", fontsize=11,
                   fontname="helv")

    # 表格页，印刷页码 2
    p3 = page(3, "2")
    p3.insert_text((70, 100), "1.3 Limiting Values", fontsize=18, fontname="hebo")
    x0, y0, w, h = 70, 130, 420, 84
    for r in range(4):
        p3.draw_line((x0, y0 + r * h / 3.), (x0 + w, y0 + r * h / 3.), width=0.8)
    for c in range(4):
        p3.draw_line((x0 + c * w / 3., y0), (x0 + c * w / 3., y0 + h), width=0.8)
    cell = [["Parameter", "Value", "Unit"],
            ["Minimum ignition energy (MIE)", "5", "mJ"],
            ["Design velocity", "0.3", "m/s"]]
    for r, row in enumerate(cell):
        for c, txt in enumerate(row):
            p3.insert_text((x0 + c * w / 3. + 6, y0 + r * h / 3. + 18),
                           txt, fontsize=10, fontname="helv")
    p3.insert_text((70, 260), "Values above shall be verified against the source.",
                   fontsize=11, fontname="helv")

    doc.save(path)
    doc.close()
    return 3


def main():
    if not EXTRACTOR.exists():
        check("找到 scripts/extract_pages.py", False, str(EXTRACTOR))
        return 1
    check("找到 scripts/extract_pages.py", True)

    if not step1_deps():
        print("\n依赖不全，先跑：pip install -r requirements.txt")
        return 1

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="pdfskill_verify_"))
    pdf = tmp / "sample.pdf"
    out = tmp / "extract"
    try:
        print()
        print("=" * 62)
        print("2/4  生成测试 PDF（3 页：封面 / 标题+正文 / 表格+数值）")
        print("=" * 62)
        n = make_test_pdf(pdf)
        check("测试 PDF 生成", pdf.exists() and pdf.stat().st_size > 1000,
              f"{n} 页, {pdf.stat().st_size/1024:.1f} KB")

        print()
        print("=" * 62)
        print("3/4  跑 extract_pages.py")
        print("=" * 62)
        r = subprocess.run(
            [sys.executable, str(EXTRACTOR), str(pdf), "--out", str(out), "--force"],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        for line in (r.stdout or "").splitlines():
            print("       " + line)
        if r.returncode != 0:
            print(r.stderr[-800:] if r.stderr else "")
        check("extract_pages.py 退出码 0", r.returncode == 0, f"rc={r.returncode}")
        if r.returncode != 0:
            return 1

        print()
        print("=" * 62)
        print("4/4  校验产物")
        print("=" * 62)

        pj = sorted((out / "pages").glob("p*.json"))
        check("逐页切片落盘", len(pj) == 3, f"{len(pj)} 个 pages/*.json")

        idx = [json.loads(l) for l in
               (out / "index.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        check("index.jsonl 行数", len(idx) == 3, f"{len(idx)} 行")

        man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        off = man.get("printed_page_offset")
        check("页码偏移探测", off == 1, f"offset={off}（期望 1，封面算前置页被跳过）")

        vals = (out / "values.txt").read_text(encoding="utf-8")
        check("数值判据扫描", "m/s" in vals and "mJ" in vals,
              f"{len(vals.splitlines())} 条命中")

        p2 = json.loads((out / "pages" / "p0002.json").read_text(encoding="utf-8"))
        has_h = ("#" in p2["text"]) and ("Chapter 1" in p2["text"])
        check("标题层级识别", has_h,
              f"p2 首行={p2['text'].splitlines()[0][:46] if p2['text'] else 'EMPTY'}")

        tbl = max((json.loads(p.read_text(encoding="utf-8"))["pipe_rows"] for p in pj), default=0)
        check("表格 pipe 行识别", tbl > 0, f"最多一页 {tbl} 行")

        p2p = p2.get("printed_page")
        check("印刷页码换算", p2p == 1, f"p2 printed_page={p2p}")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    fails = [r for r in results if not r[1]]
    print()
    print("=" * 62)
    if fails:
        print(f"结果：{len(results)-len(fails)}/{len(results)} 通过，{len(fails)} 项失败")
        for name, _, detail in fails:
            print(f"  - {name}: {detail}")
        print("\n排查：确认 pip 装到了正确的解释器 —— python -c \"import sys;print(sys.executable)\"")
        return 1
    print(f"结果：全部 {len(results)} 项通过 —— 环境就绪，可以开始处理真实 PDF 了")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())

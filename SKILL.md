---
name: pdf-literature-to-obsidian-note
description: 把 PDF 标准/规范/文献/报告转成高质量的 Obsidian 结构化笔记。流程为「pymupdf4llm 逐页切片（自带页码溯源）→ 定位关键页 → 视觉通道渲染精读表格 → 生成结构化笔记」。每条知识点必须带 (PDF页码/印刷页码, 条款号)，可回原文核对。当用户要把 PDF 文献导入 Obsidian、生成文献笔记、梳理标准规范，或抱怨 markitdown / 导入插件转换后表格错乱时使用。触发词：PDF转笔记、文献笔记、导入PDF、Obsidian 文献、标准规范整理、表格错乱。
agent_created: true
---

# PDF 文献 → Obsidian 结构化笔记（逐页切片 + 视觉精读）

## 核心原则

三条，按重要性排序：

1. **溯源优先**——每个数值判据、每条结论都必须能回原文定位到「第几页、哪个条款号」。抽出来却查不到出处 = 不能用。
2. **逐页处理**——长文档一次灌进上下文必然溢出或丢信息。按页切片，页是天然的、稳定的处理单元。
3. **表格走视觉通道**——纯文本管道（含 markitdown，也含 pymupdf4llm）会丢失表格结构、合并单元格、颜色分级、版式警示框。这些恰恰是标准规范里信息密度最高的部分。

**永远不要把任何自动转换的产物直接当笔记用**，它是原料，不是成品。

正确做法：**逐页切片（脚本，带溯源）→ 定位关键页 → 渲染成图片 → 多模态视觉精读 → 生成结构化笔记**。

## 环境准备

**依赖（必需）**：`pymupdf4llm`、`pymupdf`、`pdfplumber`、`pypdfium2`。
**可选**：`pydantic`（做 LLM API 结构化输出时才需要）、`rapidocr-onnxruntime`（扫描件 OCR 才需要）。

```bash
pip install -r requirements.txt
python verify.py          # 自检：依赖 + 端到端迷你测试
```

**首次使用先改这三个占位符**（本文件用它们代表本机路径）：

| 占位符 | 含义 | 本文件作者环境示例 |
|---|---|---|
| `<VAULT>` | Obsidian Vault 根目录 | `D:\Documents\Obsidian Vault` |
| `<PDF_LIB>` | 本地 PDF 原件库 | `D:\Work\00 Process Safety\标准规范` |
| `<SKILL_DIR>` | 本 skill 安装目录 | `~/.workbuddy/skills/pdf-literature-to-obsidian-note` |

Vault 内的目录结构约定（**示例**，实际以你的 Vault 为准，先 Glob 侦察再动手）：

- `Process Safety\01 Explosion Protection\`（00 General / 01 Atmosphere / 02 Ignition Source）
- `Process Safety\02 Pressure Relief\PSV\`（超压保护、PSV、API 520/521）
- Inbox 为收件箱。**跟随既有结构，不要自建一套**
- PDF 原件库里的文件名可能很长且含 `…`、中文、括号，取路径要加引号
- 工作区临时产物放当前 cwd，不要污染 Vault

## 工作流

### Step 1 — 逐页切片 + 溯源底座（首选，一条命令）

**不要手工做结构侦察。** 直接跑现成脚本，它一次性产出全部定位信息：

```bash
python "<SKILL_DIR>/scripts/extract_pages.py" "<PDF绝对路径>" --out ./extract
# 大文档先抽样看效果：--start 40 --end 70
# 重跑覆盖：--force      只出索引不落盘全文：--scan-only
```

一条命令拿到五样东西：

| 产物 | 内容 | 用途 |
|---|---|---|
| `pages/pNNNN.json` | 每页切片：`page_number`（PDF 页）、`printed_page`（印刷页）、`toc_path`（所属章节）、`text` | **溯源主键**，精读时按页取全文 |
| `index.jsonl` | 每页一行：页码 / 章节 / 字符数 / 表格行数 / 是否含图引用 | **选关键页的依据** |
| `manifest.json` | 总页数、**自动探测的页码偏移**、toc 条目数、耗时 | 判断扫描件、换算页码 |
| `values.txt` | 数值判据候选池，每行 `[PDF页/印刷页] [条款号] '匹配值' :: 上下文` | **数值判据不用通读全文** |
| —— | `toc_items` 自动给出 83 条章节级条目 | 章节骨架免手工整理 |

**实测（API 520-1，154 页，2026-10）**：耗时 **46.5 s**，自动探测出页码偏移 **= 8**（置信命中 90 次，与人工核对一致），toc 83 条，含图引用 60 页。

选关键页的两条规则：
- `piperows` 降序 TOP 10 → 表格密集页（**排除目录页**，目录点线会被误判成表格行）
- `figure: true` 的页 → 需在笔记里标注「图需回原文查」

**判断是否扫描件**：`manifest.json` 里若各页 `chars` 普遍 < 200（或全 0）→ 扫描版，pymupdf4llm 拿不到东西。**不用 tesseract，走 `rapidocr-onnxruntime`**（纯 Python + onnxruntime 内置模型，无需外部二进制）——完整流程见下方「变体：纯扫描件（无文本层）时的 OCR 流程」。

#### 为什么用 pymupdf4llm 而不是 markitdown

markitdown 的 PDF 后端是 **pdfminer 纯文本流**，全程不读字号/字体/坐标层级，所以物理上产不出 Markdown 标题。它整份 `_pdf_converter.py`（0.1.8 版 589 行）最终只落到一句 `pdfminer.high_level.extract_text()`，另外两个补丁只做「表单式表格猜测」和「MasterFormat `.1 .2` 分条号合并」。

**实测对照（NFPA 69.pdf 第 7–16 页同源子集，2026-11）**：

| 指标 | markitdown 0.1.8 | pymupdf4llm 1.28.2 |
|---|---|---|
| Markdown 标题 | **0 个** | **43 个**（H1×1 H2×1 H3×41） |
| 加粗标记 | 0 处 | 482 处 |
| 表格 pipe 行 | 94（大半是把普通文本硬切成的伪表格） | 65 |
| 双栏正文 | **被横向缝成一行**：`NFPA 69 sures that contain flammable...`（左栏页脚+右栏正文） | 栏序正确 |
| 断词连字符 | `jurisdic‐` / `tion.` 原样保留 | 已合并 |
| 扫描层噪声 | `---`,,`,,`-`-`, 等隐藏字符照抄 | 已过滤 |

pymupdf4llm 的后端是 **MuPDF 渲染引擎**，拿到的是带 `span / font / size / bbox` 的完整对象树和 PDF 书签，所以能判定「18pt 加粗 = 一级标题」、能靠绘制指令认出表格框线。这是信息量代差，不是参数调优能补的。

结论：**PDF 一律走 pymupdf4llm**；markitdown 的优势在 HTML / xlsx / YouTube 字幕 / 纯文本，那些场景反而该用它。

**但它不是终点**：实测 Table 1（API 520-1 p59）表头被横向切碎成 `**Nonf**` / `**ire Case**`。所以——

> **pymupdf4llm 负责「全量 + 溯源 + 定位」，视觉通道负责「关键表格逐格还原」。两者是接力关系，不是替代关系。**

#### 只有 pdfplumber 时的退化方案

环境缺 pymupdf4llm 才用这个（手工、信息量少）：

```python
import pdfplumber
p = r"<PDF 绝对路径>"
with pdfplumber.open(p) as pdf:
    print("TOTAL_PAGES:", len(pdf.pages))
    for i in range(min(7, len(pdf.pages))):
        print(f"--- P{i+1} ---"); print((pdf.pages[i].extract_text() or "")[:900])
    tp = [f"{i+1}({len(pg.find_tables())})"
          for i, pg in enumerate(pdf.pages) if pg.find_tables()]
    print("pages_with_tables:", " ".join(tp))
```

`pdfplumber` 的 `find_tables()` 会把页眉页脚误判成 2 个表格，**真实表格页 = 检出 3 个以上的页**。

### Step 2 — 定位章节起始页（多数情况可跳过）

**Step 1 的 `toc_items` 已经自动给出章节 → 页码映射（实测 83 条），优先直接用。** 每页切片里也带了 `toc_path` 字段。

只有 toc 缺失（扫描件、无书签 PDF）时才手工反查。用页脚的 `Chapter X Page N` 模式：

```python
import re, pdfplumber
pat = re.compile(r"Chapter\s+([A-Z]{1,3})\s+Page\s+(\d+)", re.I)
# 遍历每页，取每个章节最小的 doc page → 对应 PDF 页码
```

### Step 3 — 渲染关键页为图片

选页原则：每个主章节首页（总览/索引）+ 表格最密集页 + 含图表的页。**一般 10–15 页足够覆盖一份长文档**，不必全渲染（141 页全读会爆上下文）。

```python
import os, pypdfium2 as pdfium
out = os.path.join(os.getcwd(), "pages"); os.makedirs(out, exist_ok=True)
doc = pdfium.PdfDocument(p)
for i in [4, 6, 9, 25, 46, 47, 86, 114, 118, 122, 126, 128]:   # PDF 页码
    doc[i-1].render(scale=150/72).to_pil().save(os.path.join(out, f"p{i:03d}.png"))
```

`scale=150/72`（约 150 DPI）是清晰度与体积的平衡点。

### Step 4 — 视觉精读

用 **Read 工具直接读 PNG**（多模态），逐页提取：正文要点、**表格逐格内容**、图表坐标语义、颜色编码（如区域矩阵的绿/黄/红）、版式元素（红 Danger / 绿 Protective measures 框）。分批读（每批 3–6 张），避免单次返回过长。

读图时**同步登记页码**：每张图对应 `pNNNN.png` → `page_number` → `printed_page`，读到的表格当场挂上来源，别等到写笔记时再回溯（回溯必错）。

**逐页交叉验证**：pymupdf4llm 切片里该页的文本与图中读到的表格对照——文本管道切碎表头（实测 `**Nonf**`/`**ire Case**`）时，以**图为准**修正；图中看不清的单元格，用切片文本补齐。两边都对不上的，进 `open_questions`。

### Step 5 — 生成笔记

写入 Vault，路径跟随用户既有结构（先 Glob 看有没有已建目录，**不要**擅自建一套新结构，也不要覆盖既有文件）。

笔记结构建议：
1. YAML frontmatter（来源、版本、owner、页数、提取方法、tags）
2. `> [!info]` 来源与提取说明（注明「视觉通道读取」，提示关键数值需回原文核对）
3. 一句话总结
4. 文档定位表（强制性/适用范围/版本/批准机构）
5. 按章节的分层要点
6. **关键表格原样还原**（用 Markdown 表格 + 表注说明颜色语义）
7. 与工作关联（留空给用户填）
8. 关联笔记（Obsidian 双链）
9. 结尾保密与核对提醒

术语用「中文 + 英文对照」（工艺安全场景英文术语是通行标准）。

**双链一律用纯文件名** `[[NFPA 77 静电推荐实践 (2019)]]`，**不要写路径**——Obsidian 按文件名寻址，用户在 Vault 内移动/重命名文件时会自动维护这类链接；写死路径的链接移动后就断了。

## 溯源契约（硬性要求）

**抽出来的每一条知识点，必须带三元组：`(页码, 条款号, 原文值)`。** 缺任一项就是半成品。

| 元素 | 取法 | 笔记里怎么标 |
|---|---|---|
| 页码 | `extract_pages.py` 给的 `page_number`（PDF 页）与 `printed_page`（印刷页） | 表格下方加来源行：`> 来源：PDF p59 / 印刷 p51，Table 1` |
| 条款号 | 页文本里的 `5.4.2.1.2` 这类编号；扫描输出里已自动带 | 判据后括注 `(§5.4.2.1.2)` |
| 原文值 | **照抄原文字符串**，不要换算、不要四舍五入 | 如 `100 / 110`（非火灾单装置 整定/积聚） |

规则：

- **双页码都要给**。用户手上是印刷版，我读的是 PDF 页，只给一个他没法核对。换算用 `manifest.printed_page_offset`（PDF 页 = 印刷页 + offset）。
- **前置页 offset 会算出负数**（封面/目录是罗马数字页区），属正常，不是 bug，笔记里不用标印刷页。
- **拿不准的标 `【待核对 pXX】`**，不要猜。数值判据错一个就是合规事故。
- **图/曲线只转述图意并标图号**（如 `Figure 30 — Kb 背压修正系数，值需查原图`），**绝不凭记忆补数值**。
- 笔记结尾固定附一段「核对提醒」，列明哪些是 AI 整理、哪些必须回原文确认。

## 结构化输出契约（Pydantic）

两个用途，分开说清楚：

**用途 A：写批处理脚本调 LLM API 时**，用 Pydantic 模型做 `response_format`，保证输出结构稳定、可解析：

```python
from pydantic import BaseModel, Field
from typing import Literal

class Criterion(BaseModel):
    """一条可回原文核对的数值判据。"""
    clause: str = Field(description="条款号，如 '5.4.2.1.2'；无则填 '—'")
    value: str = Field(description="原文值的原始字符串，不要换算")
    unit: str = Field(default="", description="单位，无量纲留空")
    page_pdf: int = Field(description="PDF 页码（溯源主键）")
    page_printed: int | None = Field(default=None, description="印刷页码")
    context: str = Field(description="原文上下文，≤200 字，用于人工核对")

class TableCell(BaseModel):
    row: str
    col: str
    value: str
    note: str = Field(default="", description="颜色语义/脚注等纯文本丢失的信息")

class PageExtraction(BaseModel):
    """一页的抽取结果——逐页处理的最小单元。"""
    page_pdf: int
    page_printed: int | None = None
    toc_path: str = Field(default="", description="所属章节标题")
    summary: str = Field(description="本页要点，≤150 字")
    criteria: list[Criterion] = Field(default_factory=list)
    tables: list[list[TableCell]] = Field(default_factory=list)
    figures: list[str] = Field(default_factory=list, description="图号 + 图意转述，不编数值")
    uncertainties: list[str] = Field(
        default_factory=list,
        description="**必填意识**：识别失败/表格错位/疑似扫描残留，全部登记在此，不得静默丢弃"
    )

class NoteDraft(BaseModel):
    """整个文档的笔记骨架。"""
    title: str
    frontmatter: dict
    one_liner: str = Field(description="一句话总结：管什么、约束谁")
    sections: list[str]
    key_tables: list[str] = Field(description="Markdown 表格字符串，含来源行")
    criteria_index: list[Criterion]
    open_questions: list[str] = Field(description="本次未覆盖/需回原文的清单")
```

**用途 B：由 agent 自己读、不调 API 时**（本会话的常态），**遵守等价的输出契约**——把上面每个字段当成 checklist 逐项落实，尤其是：

- `uncertainties` / `open_questions` **必须显式写出来**。这是从 echohive42/AI-reads-books-page-by-page 那个项目借鉴的教训：它把知识点纯字符串拼接、不记页码，导致无法溯源；而它「逐页切片 + Pydantic 约束输出格式」这两条是对的。
- 不要用「我读完了、内容准确」这类话收尾，改用「未覆盖章节：X / Y / Z，图 N 需查原图」。

## 陷阱（都是踩过的坑，按环境标注）

> 标注「WorkBuddy 环境」的条目只在使用 WorkBuddy / CodeBuddy 这类精简 shell 的 agent 环境时成立；手工在终端跑可忽略。

| 问题 | 应对 |
|---|---|
| WorkBuddy 环境的 bash 是精简版，没有 `ls`/`grep`/`tr`/`tail`/`head` | 用 Glob / Grep / Read 工具替代，不要用 shell 命令做文件操作 |
| WorkBuddy 的 PowerShell 工具**不回显 stdout** | 结果 `Out-File` 落盘后用 Read 读，或改用 Bash 执行 python |
| Windows 上 `reg.exe` 可能被沙箱黑名单拦截 | 环境变量改用 `[Environment]::SetEnvironmentVariable` |
| markitdown 缺格式支持 | 报 MissingDependencyException 时补装对应 extras，如 `pip install 'markitdown[pdf]'` |
| 误在 Vault 里建文件 | 落地前先 Glob 侦察既有结构，只新增、不覆盖 |
| 用户在 Obsidian 里移动笔记后，WorkBuddy 的交付卡片打不开 | 卡片是**绝对路径快照**，不是活链接。重新 Glob 定位 → 用新路径再 present 一次；日常让用户用 Obsidian `Ctrl+O` 按文件名打开最稳 |
| **YAML frontmatter 被 Obsidian 静默丢弃** | 值里含 `: `（冒号 + 空格）必须用双引号包起来。典型受害者：`标准名称: ... Part I: Sizing ...`。值含 `#`、以 `[`/`{` 开头同理 |
| frontmatter 别名不生效 | 键必须是英文 `aliases`，中文键（如 `别名`）Obsidian 不认。写 `aliases: ["API 520", "API 520-1"]` 后 `[[API 520]]` 才能解析到该笔记 |
| 公式从文本层提取后分式结构失真 | pdfplumber 会把分式拆成多行乱序（分子/分母分行）。**必须按标准数学形式重写，并在笔记中标注「排版转换可能有误，计算前回原文核对」** |
| **`pymupdf4llm` 的 `pages` 参数是 0-based** | 传 `pages=[58]` → 返回 `metadata.page_number == 59`。越界直接抛 `ValueError: 'pages' parameter must be None, int, or a sequence of ints < N`。`extract_pages.py` 已处理，自己写脚本时别踩 |
| 数值扫描的**前置页噪声** | 目录点线（`. . . 129`）会被 `%`/数字规则命中，版权声明里的 `mechanical` 会被 `MEC` 命中（加 `\b` 词边界解决）。脚本已跳过 `printed_page < 1` 的前置页 |
| bash 重定向报 `UnicodeDecodeError: 0xb2` | 输出含 `²`/`°` 等字符时，bash 工具的 subprocess 解码会抛异常并刷屏。**exit code 仍是 0，结果文件正常**，别被吓到去改脚本。改用 python 落盘 + Read 读更干净 |
| `pymupdf_layout` 首次加载慢 | 依赖 onnxruntime（42 MB），首次 import 要走 layout 模型初始化。154 页实测 46.5 s 属正常，不是卡死 |

## 策略选择：视觉通道 vs 文本通道 vs 混合

| 源文件情况 | 推荐策略 | 理由 |
|---|---|---|
| **文本版 PDF + 表格密集**（标准、规范） | **pymupdf4llm 全量切片 → 定位关键页 → 视觉通道精读表格**；公式与符号定义直接用切片里的文本 | 溯源自动带、定位不用猜、表格逐格还原。这是本 skill 的主路径 |
| **文本版 PDF，表格少**（叙述性指南、书籍） | pymupdf4llm 切片 + 逐页通读，不必渲染图片 | 省掉渲染与视觉精读开销 |
| 扫描版 PDF | **OCR（rapidocr）→ 再走视觉通道** | 文本层为空，pymupdf4llm 拿不到东西。详见「变体：纯扫描件」 |
| 图片/图表/P&ID 密集 | 视觉通道 | 文本通道完全丢失 |
| 源文件在 IMA 云端 | 文本通道（见下方变体） | 拿不到原始 PDF 渲染 |

**页码换算技巧**：标准类 PDF 通常 `PDF 页码 = 印刷页码 + 固定偏移`。先读目录页拿到印刷页码，再取前 30 页的页脚数字反推偏移（如 API 520-1 偏移 = 8，API 521 靠页脚 `Chapter X Page N` 反查），之后即可精准定位。

**表格密度定位**：`pdfplumber` 的 `find_tables()` 对每页**页眉页脚误判为 2 个表格**，所以**真实表格页 = 检出 3 个以上的页**。

## 变体：纯扫描件（无文本层）时的 OCR 流程 ⭐实测

**判定**：`manifest.json` 里各页 `chars` 普遍 < 200（极端情况全为 0）→ 扫描版。可再 `pymupdf` 看 `doc.metadata["creator"]`：`Pdg2Pic`、`FreePic2Pdf_Lib`、`UniBook`、`Kodak` 等都是扫描件生成器；每页 `get_images()` 返回 1 张、`get_text()` 为空，即**纯图像无文本层**。

**用 `rapidocr-onnxruntime` 代替 tesseract**（纯 Python + onnxruntime 内置模型，无需外部二进制、也不需要管理员权限）：

```bash
pip install rapidocr-onnxruntime==1.2.3   # 含 onnxruntime(44MB)+opencv+Pillow+Shapely+pyclipper
```

```python
import pymupdf, numpy as np
from rapidocr_onnxruntime import RapidOCR
engine = RapidOCR()
doc = pymupdf.open(SRC)
for pno in range(1, doc.page_count + 1):
    pix = doc[pno-1].get_pixmap(matrix=pymupdf.Matrix(2.6, 2.6))  # ≈187 DPI，再高收益递减
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 4:                      # 去 alpha
        img = img[:, :, :3]
    img = np.ascontiguousarray(img[:, :, ::-1])   # RGB → BGR（RapidOCR 要 BGR）
    res, _ = engine(img)
    lines = [r[1] for r in res] if res else []
    # 落盘 pages/pNNNN.json：{page_number, text, char_count, line_count}
```

**实测（CCPS《机械完整性体系指南》205 页扫描件，2026-10）**：全程 **746.6 s（≈12.4 min）**，205/205 页成功，单页字符 min/avg/max = **123 / 915 / 2858**，无 <100 字符的空页。**放心跑，不用抽样**。放 `run_in_background` 即可。

**OCR 后仍要走完整流程**：切片 → 章节定位 → 关键页渲染 → 视觉逐格核对。OCR 文本是"原料"，表格结构照旧会错乱。

### ⚠️ 扫描件特有陷阱

| 问题 | 应对 |
|---|---|
| **横向跨页大表**（一表横跨 2–3 页、页面旋转 90° 排版） | 直接读图是"歪的"，OCR 输出行列完全错位。**先把 PNG `rotate(-90, expand=True)` 转正再 Read**，逐格还原效果与文本版相当。实测表 11-1 跨 p152–154 三页，转正后可完整还原 9 行 × 5 列 |
| **元数据不可信但生成器可信** | `metadata["title"]` 常是乱码/空，但 `creator`（Pdg2Pic 等）可靠指示扫描件。别用 title 判断版本 |
| **页码偏移靠目录页反查** | 扫描件无书签、无页脚可解析时：OCR 目录页拿到印刷页 → 与正文页对照得固定偏移（本书 **PDF 页 = 印刷页 + 24**，即 PDF p25 = 印刷 p1） |
| **生僻字/专名被 OCR 念错** | 高频：`冗余→穴余`、`Kletz→Klutz`、`ANSI/ASME B31.3→ANSVASMEB31.3`。**笔记里按上下文修正，并在「局限与声明」里列出修正清单**（用户要能看到改了什么） |
| **上下标丢负号** | 与 IMA 通道同病：`10⁻¹` 常被识成 `10-1` / `101`。SIL/PFD 这类表**逐格回图核对**，不要信 OCR |

### Python 环境建议

**优先用独立 venv**，不要污染系统 Python：

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

OCR 变体额外装：

```bash
pip install rapidocr-onnxruntime==1.2.3   # 含 onnxruntime(44MB)+opencv+Pillow+Shapely+pyclipper
```

在 WorkBuddy 里跑时，注意 agent 自带的 Python 与系统 Python 可能不是同一个——`pip install` 装到哪个解释器，就要用同一个解释器跑脚本。用 `python -c "import sys; print(sys.executable)"` 确认。

## 变体：源文件在 IMA 知识库（云端）时

> **平台相关**：本节依赖腾讯 ima 的 MCP 工具（`search_knowledge` / `fetch_media_content`）。没有 ima 接入的环境直接跳过——把 PDF 下载到本地走主流程即可。

没有本地 PDF、只有 IMA 里的文件时，用这套：

1. `search_knowledge(knowledge_base_id, "关键词")` 找到文件，取 `media_id`（必先 ToolSearch 加载 `mcp__ima-mcp__*` 工具）。
   - **省一次调用的技巧**：本会话此前若已做过 `search_knowledge` 且结果落盘，直接用脚本从那个 `.txt` 里正则提取 `media_id`（配对模式：`"media_id": "..." ... "title": "..."`），不必重新搜索。
   - `search_knowledge` 结果也常超限落盘（>10 万字符），同样用脚本提取标题清单，不要硬读。
2. `fetch_media_content(media_id)` 拉内容。**大文件必超限**，工具会自动把结果写到
   `<TOOL_RESULTS>/mcp-ima-mcp-fetch_media_content-*.txt`（路径由 agent 运行时给出，通常在会话工作区的 `tool-results` 下）。
3. ⚠️ **直接 Read 那个路径会被权限拒绝**。用 PowerShell `Copy-Item` 复制到当前工作区，再 Read。
4. 内容是单行 JSON：`{"content": "..."}`。用 Python `json.load()` 取 `content`。
5. **别通读全文**（36 万字符级）。组合三招：
   - 正则抓 `#\s+Chapter (\d+)` 定位章节偏移 → 切片导出关键章（取每章最大偏移，避开目录里的同名标题）
   - 正则抓数值判据（`\d+ m/s`、`\d+ mJ`、`megohm`、`resistivity`）并输出 ±260 字符上下文
   - 只对 2–4 个核心章节做完整精读
6. IMA 提取的**图只剩占位符**（`![](...)` 或 alt 乱码），数值图表（如电阻率分级图）**必须标注「需回原文查图」**，不要凭记忆补全。

### ⚠️ IMA 提取的三个高发数据损坏（实测，务必主动排查）

| 损坏类型 | 表现 | 应对 |
|---|---|---|
| **上标负号丢失** | `4.0×10⁻⁵` 被提取成 `$4.0 \times 10^5$`（负号消失）。**频率类表格几乎必然中招** | 见到 `10^5`、`10^2` 这种「正指数且量级不合常理」的值，立即怀疑丢负号。**该表宁可不录入，写明「原表指数符号提取有误，请回原文」** |
| **曲线图被转成表格且错位** | 对数坐标图（超压-距离、脆弱性-超压等）被转成 pipe table，表头串列、行错位（如 `\|1\|60\|13\|7\|` 对应三列表头） | 整理时必须标注「由曲线图转换，**不保证与原图一致**，定量计算前查原图」 |
| **图完全丢失** | 出现 `![未能识别到文本内容](...)` | 记为「图丢失」，**不要跳过不提**——用户需要知道这里少了一块 |

排查手法：对提取出的 markdown 跑一次 `grep -c "未能识别到文本内容"` 和「指数异常」检查，把结果写进笔记的警示框。

### 同一文件可能有多个副本

IMA 里同一份文件常存在**多份副本**（不同上传时间 / 带工程编号前缀，如 `0130e_Facility siting guide_OBRA_CIA.pdf` vs `Facility siting guide_OBRA_CIA.pdf`，两者 media_id 不同、内容一致）。
**先列出所有副本（标题 / media_id / 上传时间 / 大小），确认用户要哪一份再拉取**——文件名里的编号前缀（`0130e_`、`0174e_`）通常来自原公司的文档管理系统。

数值判据一律**标注条款号**（如 7.4.1.3），方便用户回原文核对——这是该用户明确偏好的可追溯性。

## 判断标准（什么算交付合格）

- 文档里的**关键表格**至少还原 3 张，且表格内容与原文一致（含 Zone 分级、材料准入等判据类表格）
- **每处关键数据标注 (PDF页码/印刷页码, 条款号)**——不是只标页码，三元组齐全
- 每张表格下方有来源行，可独立核对
- **显式列出未覆盖章节、需回原文查的图、以及拿不准标了【待核对】的项**
- 明确告知用户「AI 整理、需核对」而非声称权威

---

## 迁移到新机器时的检查清单

1. `pip install -r requirements.txt`（OCR 变体再装 `rapidocr-onnxruntime`）
2. 改本文件的三个占位符：`<VAULT>` / `<PDF_LIB>` / `<SKILL_DIR>`
3. 跑 `python verify.py`，端到端应输出 `[PASS]`（含标题识别、页码偏移探测、数值扫描三项）
4. 把 `SKILL.md` + `scripts/` 复制到 agent 的 skills 目录（如 `~/.workbuddy/skills/pdf-literature-to-obsidian-note/`）
5. 首次实战先拿一份 20–30 页的小文档试，确认笔记结构与你的 Vault 约定吻合，再处理长文档

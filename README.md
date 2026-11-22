# PDF 文献 → Obsidian 结构化笔记（技能包）

把 PDF 标准 / 规范 / 文献 / 报告转成**可溯源**的 Obsidian 笔记：每条知识点都带 `(PDF页码, 印刷页码, 条款号)` 三元组，关键表格逐格还原，拿不准的显式标注。

面向工艺安全、工程标准、技术规范这类**表格密集 + 双栏排版 + 需要回原文核对**的文档。

---

## 快速开始

### Windows

```powershell
# 在当前解压出来的目录里执行
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

装到自定义目录 / 跳过依赖：

```powershell
.\install.ps1 -Target "D:\my-agent\skills\pdf-note"
.\install.ps1 -SkipDeps
```

### macOS / Linux / Git Bash

```bash
chmod +x install.sh
./install.sh                       # 默认装到 ~/.workbuddy/skills/
./install.sh /path/to/skills/dir   # 自定义目录
SKIP_DEPS=1 ./install.sh           # 只拷文件
```

### 只想手动装（不跑脚本）

1. `pip install -r requirements.txt`
2. 把 `SKILL.md` 和 `scripts/` 复制到 agent 的 skills 目录：

| 环境 | 默认 skills 目录 |
|---|---|
| WorkBuddy / CodeBuddy | `~/.workbuddy/skills/pdf-literature-to-obsidian-note/` |
| 其他支持 SKILL.md 约定的 agent | 按其文档放置，保持 `SKILL.md` 在根、脚本在 `scripts/` |

3. `python verify.py` 确认环境就绪

---

## 装完必须改的三个占位符

打开 `SKILL.md`，把这三处换成你自己机器上的真实路径：

| 占位符 | 含义 | 示例 |
|---|---|---|
| `<VAULT>` | Obsidian Vault 根目录 | `D:\Documents\Obsidian Vault` |
| `<PDF_LIB>` | 本地 PDF 原件库 | `D:\Work\00 Process Safety\标准规范` |
| `<SKILL_DIR>` | 本技能安装目录 | `~/.workbuddy/skills/pdf-literature-to-obsidian-note` |

改完重启 agent，技能即生效。

---

## 目录结构

```
pdf-obsidian-skill/
├── SKILL.md              技能本体（方法论 + 契约 + 陷阱表，约 350 行）
├── scripts/
│   └── extract_pages.py  逐页切片 + 页码溯源底座（一条命令出 4 种产物）
├── requirements.txt      必需依赖 + 可选项（注释形式）
├── verify.py             环境自检：11 项断言，含端到端迷你测试
├── install.ps1           Windows 安装
├── install.sh            macOS / Linux 安装
└── README.md             本文件
```

---

## 它怎么工作

```
PDF
 ├─ Step 1  逐页切片（脚本）      → pages/pNNNN.json + index.jsonl + manifest.json + values.txt
 ├─ Step 2  定位关键页            → 用 piperows 降序找表格密集页，figure:true 标记含图页
 ├─ Step 3  关键页渲染成 PNG      → 约 150 DPI，10–15 页足够覆盖长文档
 ├─ Step 4  视觉精读              → 多模态读图，表格逐格还原，与文本切片交叉验证
 └─ Step 5  生成笔记              → YAML frontmatter + 分层要点 + 表格来源行 + 双链
```

三条核心原则：

1. **溯源优先**——查不到出处的数据不能用
2. **逐页处理**——长文档一次灌进上下文必然溢出或丢信息
3. **表格走视觉通道**——纯文本管道会丢表格结构、合并单元格、颜色分级

自动转换的产物是**原料，不是成品**。

---

## 自检脚本看什么

`python verify.py` 会现场生成一份 3 页测试 PDF（封面 + 标题正文 + 表格数值），跑完整流程后断言 11 项：

- 4 个依赖是否可用及版本
- 逐页 JSON、`index.jsonl`、`manifest.json`、`values.txt` 是否都生成
- 页码偏移探测是否正确（测试件期望 offset=1）
- **标题层级是否被识别**（`## Chapter 1`）
- 表格 pipe 行是否被识别
- 印刷页码换算是否正确
- 数值判据扫描是否命中（`m/s`、`mJ`）

全 PASS 才算环境就绪。有 FAIL 时先确认 `pip` 装到了正在跑脚本的那个解释器：

```bash
python -c "import sys; print(sys.executable)"
```

> 如果在老旧 Windows 控制台里看到中文乱码，先执行 `chcp 65001` 切到 UTF-8 代码页，或用 Windows Terminal。

---

## 平台适配

核心流程是**通用**的——只要你的 agent 能跑 Python、能读图，就能用。个别小节带平台色彩：

| 部分 | 依赖 | 没有时怎么办 |
|---|---|---|
| Step 1–5 主流程 | Python + 支持多模态读图的 agent | — |
| 「源文件在 IMA 知识库」变体 | 腾讯 ima MCP 工具 | 跳过，把 PDF 下载到本地走主流程 |
| 陷阱表里标「WorkBuddy 环境」的条目 | WorkBuddy / CodeBuddy 的精简 shell | 忽略，手工在终端跑不受影响 |

`SKILL.md` 的 frontmatter 遵循通用 skills 约定（`name` + `description`），Claude Code、CodeBuddy 等支持该约定的 agent 可直接加载。

---

## 适用与不适用

| 情况 | 建议 |
|---|---|
| 文本版 PDF + 表格密集（标准、规范） | ✅ 主场景，走完整五步 |
| 文本版 PDF、表格少（指南、书籍） | ✅ 可以省掉渲染，直接逐页读切片 |
| 纯扫描件（无文本层） | ✅ 先 OCR（`rapidocr-onnxruntime`），再走视觉通道；205 页实测约 12 分钟 |
| 图表 / P&ID 密集 | ✅ 必须视觉通道 |
| 只需要把 PDF 转成纯文本喂给 LLM | ⚠️ 用更轻的工具就行，不需要这套流程 |
| 想要"一键全自动、不核对" | ❌ 这套流程的前提就是人工/视觉核对 |

---

## 已知限制

- **PDF 里没有的数值，笔记里也不会有**。图/曲线只转述图意并标图号，不凭记忆补数值。
- pymupdf4llm 会把表格表头横向切碎（实测 `**Nonf**` / `**ire Case**`），所以关键表格必须回图核对。
- 扫描件 OCR 有固定复发错误：上下标丢负号（`10⁻¹`→`10-1`）、生僻专名（`Kletz`→`Klutz`）。笔记里要列修正清单。
- 页码偏移会自动探测，但封面/目录用罗马数字时前置页会算出负数，属正常。

---

## 版本

- 技能版本：v1.0（2026-11 封装）
- 依赖基线：pymupdf4llm 1.28.2 / pymupdf 1.28.2 / pdfplumber 0.11.10
- 已实测环境：Windows + Python 3.14，端到端 11/11 通过

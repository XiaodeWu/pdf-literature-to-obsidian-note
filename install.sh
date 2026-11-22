#!/usr/bin/env bash
# 安装 pdf-literature-to-obsidian-note 技能（macOS / Linux / Git Bash）
#
# 用法：
#   ./install.sh                          # 装到 ~/.workbuddy/skills/
#   ./install.sh /path/to/skills/dir      # 装到指定目录
#   SKIP_DEPS=1 ./install.sh              # 只拷文件，不装依赖
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:-$HOME/.workbuddy/skills/pdf-literature-to-obsidian-note}"

echo "== pdf-literature-to-obsidian-note installer =="
echo "Source: $SRC"
echo "Target: $TARGET"
echo

for f in SKILL.md scripts/extract_pages.py requirements.txt verify.py; do
  if [ ! -f "$SRC/$f" ]; then
    echo "[FAIL] 缺少文件: $f"
    exit 1
  fi
done

if [ -e "$TARGET" ]; then
  BACKUP="$TARGET.bak-$(date +%Y%m%d-%H%M%S)"
  cp -R "$TARGET" "$BACKUP"
  echo "[i] 已备份原安装到: $BACKUP"
fi

mkdir -p "$TARGET/scripts"
cp "$SRC/SKILL.md" "$TARGET/SKILL.md"
cp "$SRC/requirements.txt" "$TARGET/requirements.txt"
cp "$SRC/verify.py" "$TARGET/verify.py"
cp "$SRC/scripts/extract_pages.py" "$TARGET/scripts/extract_pages.py"
[ -f "$SRC/README.md" ] && cp "$SRC/README.md" "$TARGET/README.md"
echo "[OK] 文件已复制"

if [ "${SKIP_DEPS:-0}" = "1" ]; then
  echo "[i] SKIP_DEPS=1，跳过依赖安装"
else
  PY="${PYTHON:-python3}"
  command -v "$PY" >/dev/null 2>&1 || PY=python
  echo
  echo "[i] 使用解释器: $("$PY" -c 'import sys; print(sys.executable)')"
  echo "[i] 安装依赖 ..."
  if [ -n "${PIP_MIRROR:-}" ]; then
    "$PY" -m pip install -r "$SRC/requirements.txt" -i "$PIP_MIRROR"
  else
    "$PY" -m pip install -r "$SRC/requirements.txt"
  fi
  echo "[OK] 依赖已安装"

  echo
  echo "[i] 运行自检 ..."
  "$PY" "$SRC/verify.py" || echo "[WARN] 自检未全部通过，见上方输出"
fi

cat <<'EOF'

== 完成 ==
下一步：
  1. 编辑 SKILL.md，把 <VAULT> / <PDF_LIB> / <SKILL_DIR> 换成你自己的路径
  2. 重启 agent，让新技能被加载
  3. 先拿一份 20–30 页的小 PDF 试跑
EOF

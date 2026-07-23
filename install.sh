#!/usr/bin/env bash
# 供应链结算对账插件 —— 一键安装
set -euo pipefail
PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_NAME="supply-chain-settlement"

echo "【1/4】检测 Python 环境..."
command -v python3 >/dev/null 2>&1 || { echo "✗ 未找到 python3，请先安装 Python 3.10+"; exit 1; }
if ! python3 -c "import openpyxl" >/dev/null 2>&1; then
  echo "      缺少 openpyxl，正在安装..."
  python3 -m pip install --user openpyxl
fi
echo "      ✓ python3 $(python3 -c 'import sys;print(sys.version.split()[0])') + openpyxl 就绪"

echo "【2/4】安装 Skill 到 Codex（~/.codex/skills）..."
mkdir -p "$HOME/.codex/skills"
ln -sfn "$PLUGIN_DIR/skills/$SKILL_NAME" "$HOME/.codex/skills/$SKILL_NAME"
echo "      ✓ ~/.codex/skills/$SKILL_NAME -> 本插件"
if [ -d "$HOME/.agents" ]; then
  mkdir -p "$HOME/.agents/skills"
  ln -sfn "$PLUGIN_DIR/skills/$SKILL_NAME" "$HOME/.agents/skills/$SKILL_NAME"
  echo "      ✓ 同时安装到 ~/.agents/skills"
fi

echo "【3/4】安装 Plugin 清单到 ~/.codex/plugins..."
mkdir -p "$HOME/.codex/plugins"
ln -sfn "$PLUGIN_DIR" "$HOME/.codex/plugins/$SKILL_NAME"
echo "      ✓ ~/.codex/plugins/$SKILL_NAME -> 本插件"

echo "【4/4】初始化工作区..."
"$PLUGIN_DIR/bin/scs" init

echo ""
echo "✓ 安装完成！"
echo ""
echo "接下来："
echo "  1. 把供应链群发的 Excel 放进：$PLUGIN_DIR/workspace/settlement-inbox/"
echo "  2. 在 Codex 里直接说：\"扫描今天供应链发来的 Excel\" 或 \"帮我生成结算预览\""
echo "  3. 首次使用请先导入历史台账，见 README.md「首次使用」一节"

#!/usr/bin/env bash
# 供应链结算对账插件 —— 一键安装（总控 + 2 子技能 + MCP 工具）
set -euo pipefail
PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_NAME="supply-chain-settlement"
SKILLS=(supply-chain-settlement scs-reconcile scs-ledger)

echo "【1/5】检测 Python 环境..."
command -v python3 >/dev/null 2>&1 || { echo "✗ 未找到 python3，请先安装 Python 3.10+"; exit 1; }
if ! python3 -c "import openpyxl" >/dev/null 2>&1; then
  echo "      缺少 openpyxl，正在安装..."
  python3 -m pip install --user openpyxl
fi
echo "      ✓ python3 $(python3 -c 'import sys;print(sys.version.split()[0])') + openpyxl 就绪"

echo "【2/5】安装技能到 Codex（总控 + 2 子技能）..."
mkdir -p "$HOME/.codex/skills"
for s in "${SKILLS[@]}"; do
  ln -sfn "$PLUGIN_DIR/skills/$s" "$HOME/.codex/skills/$s"
  echo "      ✓ ~/.codex/skills/$s"
done
if [ -d "$HOME/.agents" ]; then
  mkdir -p "$HOME/.agents/skills"
  for s in "${SKILLS[@]}"; do
    ln -sfn "$PLUGIN_DIR/skills/$s" "$HOME/.agents/skills/$s"
  done
  echo "      ✓ 同时安装到 ~/.agents/skills"
fi

echo "【3/5】安装 Plugin 清单到 ~/.codex/plugins..."
mkdir -p "$HOME/.codex/plugins"
ln -sfn "$PLUGIN_DIR" "$HOME/.codex/plugins/$PLUGIN_NAME"
echo "      ✓ ~/.codex/plugins/$PLUGIN_NAME -> 本插件"

echo "【4/5】注册 MCP 工具（mcp/server.py）..."
if python3 -c "import mcp" >/dev/null 2>&1; then
  echo "      ✓ Python mcp SDK 就绪"
else
  echo "      ⚠ 未检测到 Python mcp SDK。需要 MCP 工具时执行："
  echo "        python3 -m pip install --user 'mcp[cli]'"
  echo "        （不装也不影响 CLI 和技能使用）"
fi
CODEX_CONFIG="$HOME/.codex/config.toml"
touch "$CODEX_CONFIG"
if ! grep -q "^\[mcp_servers\.scs\]" "$CODEX_CONFIG"; then
  {
    echo ""
    echo "[mcp_servers.scs]"
    echo "command = \"python3\""
    echo "args = [\"$PLUGIN_DIR/mcp/server.py\"]"
  } >> "$CODEX_CONFIG"
  echo "      ✓ 已注册到 $CODEX_CONFIG（[mcp_servers.scs]）"
else
  echo "      ✓ $CODEX_CONFIG 已有 [mcp_servers.scs]，跳过"
fi

echo "【5/5】初始化工作区..."
"$PLUGIN_DIR/bin/scs" init

echo ""
echo "✓ 安装完成！"
echo ""
echo "接下来："
echo "  1. 把供应链群发的 Excel 放进：$PLUGIN_DIR/workspace/settlement-inbox/"
echo "  2. 在 Codex 里直接说：\"扫描今天供应链发来的 Excel\" 或 \"帮我生成结算预览\""
echo "  3. 首次使用请先导入历史台账，见 README.md「首次使用」一节"
echo "  4. Claude Code 用户可改用 marketplace 安装，见 README.md「安装」一节"

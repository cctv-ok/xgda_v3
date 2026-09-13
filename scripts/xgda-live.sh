#!/usr/bin/env bash
# =============================================================
# XGDA 一键真 9:25 跑（Git Bash / WSL）
#
# 用法：
#   bash scripts/xgda-live.sh                  阻塞等到今日 09:25:01
#   bash scripts/xgda-live.sh --once           立即跑
#   bash scripts/xgda-live.sh --once --no-l2   关闭 L2 校验
# =============================================================
set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
cd "$PROJECT_ROOT"

PY_WIN=".venv/Scripts/python.exe"
PY_NIX=".venv/bin/python"

if [ -f "$PY_WIN" ]; then
    PY="$PY_WIN"
elif [ -f "$PY_NIX" ]; then
    PY="$PY_NIX"
else
    echo "[xgda-live] ERROR: 找不到 venv python" >&2
    exit 1
fi

echo "[xgda-live] 启动..."
echo "[xgda-live] Python: $PY"
echo "[xgda-live] 现在: $(date '+%Y-%m-%d %H:%M:%S %A')"
echo

PYTHONIOENCODING=utf-8 "$PY" scripts/run_real_live.py --once --l2-verify "$@"

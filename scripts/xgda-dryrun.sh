#!/usr/bin/env bash
# =============================================================
# XGDA 一键 dry-run 链路验证（Git Bash / WSL）
#
# 用法：
#   bash scripts/xgda-dryrun.sh                   默认（开 L2 verify）
#   bash scripts/xgda-dryrun.sh --no-l2           关闭 L2 验证
#   bash scripts/xgda-dryrun.sh --xg-weight 0.7   调整 XGDA 权重（0-1）
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
    echo "[xgda-dryrun] ERROR: 找不到 venv python" >&2
    echo "                 请先建 venv：python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt" >&2
    exit 1
fi

# 参数清洗：抽出 --no-l2 / --xg-weight，其余透传
L2_FLAG="--l2-verify"
FORWARD_ARGS=()
SKIP_NEXT=0
for arg in "$@"; do
    if [ $SKIP_NEXT -eq 1 ]; then SKIP_NEXT=0; continue; fi
    case "$arg" in
        --no-l2)      L2_FLAG="" ;;
        --l2-verify)  : ;;  # 默认已带，显式忽略
        --xg-weight)  FORWARD_ARGS+=("$arg"); SKIP_NEXT=1; shift_for_value="${arg}"; continue ;;
        # 真正的值在下一轮，由 "$@" 自然收集
        *)            FORWARD_ARGS+=("$arg") ;;
    esac
done
# 重新拼：把 --xg-weight + 值一并透传
REST_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --no-l2) ;;  # 已处理
        --l2-verify) ;;
        *) REST_ARGS+=("$arg") ;;
    esac
done

echo "[xgda-dryrun] 开始 mock 链路验证..."
echo "[xgda-dryrun] Python: $PY"
echo "[xgda-dryrun] L2 标志: ${L2_FLAG:-(关闭)}"
echo

PYTHONIOENCODING=utf-8 "$PY" scripts/run_real_live.py --dry $L2_FLAG "${REST_ARGS[@]}"


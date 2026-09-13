#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_smoke.py：离线冒烟测试入口（绕过 pytest，直接跑）

用法：
    python scripts/run_smoke.py
"""
import sys
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def main():
    """调用 pytest 跑 tests/ 下的全部测试，无 pytest 时 fallback 到内置 import 测试"""
    try:
        import pytest
    except ImportError:
        print("⚠️ pytest 未安装，至少做核心 import 校验…")
        try:
            import xgda
            from xgda.signal import xgda_signal
            from xgda.scoring import calc_score, _sharpe_transform
            from xgda.search import grid_search, genetic_search, walk_forward_validation
            from xgda.data_source import load_mock, load_tdx7
            from xgda.real import select_at_open, DailyRunner
            print("[fallback] ✓ 核心 import 全部成功")
            return 0
        except Exception as e:
            print(f"[fallback] ✗ import 失败: {e}")
            return 1

    # pytest 模式
    rc = pytest.main([
        str(PROJECT_ROOT / "tests"),
        "-v", "--tb=short",
        "--color=yes",
    ])
    return rc


if __name__ == "__main__":
    rc = main()
    sys.exit(rc)

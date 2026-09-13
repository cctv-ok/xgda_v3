"""test_signal.py：xgda_signal 单元测试"""
import math
import pandas as pd
import pytest

from xgda.signal import xgda_signal


class TestXgdaSignal:
    def test_basic_filter(self):
        df = pd.DataFrame({
            "code": ["600000", "600000", "600000"],
            "datetime": pd.date_range("2025-01-02", periods=3),
            "base_ok": [True, True, True],
            "circ_value_z": [10.0, 25.0, 50.0],
        })
        out = xgda_signal(df, {"z_min": 15, "z_max": 40})
        # 只有第二行 z=25 在 [15, 40] → 1
        assert list(out) == [0, 1, 0]

    def test_base_ok_required(self):
        """base_ok=False 的行即使 z 在区间内也不选"""
        df = pd.DataFrame({
            "code": ["600000", "688000"],
            "datetime": pd.date_range("2025-01-02", periods=2),
            "base_ok": [True, False],
            "circ_value_z": [20.0, 20.0],
        })
        out = xgda_signal(df, {"z_min": 10, "z_max": 30})
        # 688000 会被 base_ok=False 滤掉
        assert list(out) == [1, 0]

    def test_nan_handling(self):
        """z=NaN 应被排除"""
        df = pd.DataFrame({
            "code": ["600000", "600000"],
            "datetime": pd.date_range("2025-01-02", periods=2),
            "base_ok": [True, True],
            "circ_value_z": [float("nan"), 20.0],
        })
        out = xgda_signal(df, {"z_min": 10, "z_max": 30})
        assert list(out) == [0, 1]

    def test_all_nan_warning(self, capsys):
        """全 NaN 时打印警告一次"""
        df = pd.DataFrame({
            "code": ["600000"] * 3,
            "datetime": pd.date_range("2025-01-02", periods=3),
            "base_ok": [True, True, True],
            "circ_value_z": [float("nan")] * 3,
        })
        out = xgda_signal(df, {"z_min": 10, "z_max": 30})
        assert list(out) == [0, 0, 0]
        captured = capsys.readouterr()
        assert "⚠️ circ_value_z 全 NaN" in captured.out

    def test_boundary_inclusive(self):
        """z_min 和 z_max 端点包含（>= 与 <=）"""
        df = pd.DataFrame({
            "code": ["600000"] * 3,
            "datetime": pd.date_range("2025-01-02", periods=3),
            "base_ok": [True, True, True],
            "circ_value_z": [10, 30, 40],
        })
        out = xgda_signal(df, {"z_min": 10, "z_max": 30})
        # 边界 10 和 30 应入选
        assert list(out) == [1, 1, 0]

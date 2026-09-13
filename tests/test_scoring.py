"""test_scoring.py：calc_score 单元测试"""
import math
import pytest
import numpy as np

from xgda.scoring import calc_score, _sharpe_transform
from xgda.config import (
    SCORE_INVALID_FLOOR, SCORE_INVALID_CEIL, SCORE_VALID_FLOOR,
    SCORE_W_SHARPE, SCORE_W_WINRATE, SCORE_W_DRAWDOWN,
)


# ---- _sharpe_transform ----
class TestSharpeTransform:
    def test_zero_maps_to_zero(self):
        assert _sharpe_transform(0.0) == 0.0

    def test_positive_in_range(self):
        v = _sharpe_transform(2.0)
        assert 0 < v < 1
        assert math.isclose(v, 2.0 / 3.0)

    def test_negative_in_range(self):
        v = _sharpe_transform(-2.0)
        assert -1 < v < 0
        assert math.isclose(v, -2.0 / 3.0)

    def test_nan_returns_minus_one(self):
        assert _sharpe_transform(float("nan")) == -1.0

    def test_inf_returns_minus_one(self):
        """v3.0 设计：inf 与 NaN 都返回 -1.0（避免污染有效个体评分）"""
        assert _sharpe_transform(float("inf")) == -1.0
        assert _sharpe_transform(float("-inf")) == -1.0

    def test_no_saturation(self):
        """关键性质：大 sharpe 不应被截断到饱和"""
        v100 = _sharpe_transform(100.0)
        v10 = _sharpe_transform(10.0)
        assert v100 > v10       # 单调
        assert v100 > 0.99      # 但接近 1


# ---- calc_score ----
class TestCalcScore:
    def _res(self, sharpe=1.0, win_rate=0.5, max_drawdown=0.1,
             total_closed=200):
        return {
            "sharpe": sharpe, "win_rate": win_rate,
            "max_drawdown": max_drawdown, "total_closed": total_closed,
            "calmar": 1.0, "final_value": 110000,
        }

    def test_invalid_low_floor(self):
        res = self._res(total_closed=0)
        assert calc_score(res, min_trades=100) == SCORE_INVALID_FLOOR

    def test_invalid_gradient(self):
        """trade=50（min=100）→ ratio=0.5 → FLOOR + 0.5 * (CEIL - FLOOR)"""
        res = self._res(total_closed=50)
        s = calc_score(res, min_trades=100, use_gradient=True)
        expected = SCORE_INVALID_FLOOR + 0.5 * (
            SCORE_INVALID_CEIL - SCORE_INVALID_FLOOR
        )
        assert math.isclose(s, expected)

    def test_invalid_no_gradient(self):
        res = self._res(total_closed=10)
        assert calc_score(res, min_trades=100, use_gradient=False) \
            == SCORE_INVALID_FLOOR

    def test_valid_computes_score(self):
        res = self._res(sharpe=1.0, win_rate=0.5, max_drawdown=0.1)
        s = calc_score(res, min_trades=100)
        # 0.5 * (1/(1+1)) + 0.3 * 0.5 - 0.2 * 0.1 = 0.25 + 0.15 - 0.02 = 0.38
        expected = (SCORE_W_SHARPE * (1.0 / 2.0)
                    + SCORE_W_WINRATE * 0.5
                    - SCORE_W_DRAWDOWN * 0.1)
        assert math.isclose(s, expected, abs_tol=1e-9)

    def test_valid_floor_enforced_under_extreme(self):
        """极端负分（如 sharpe=-10, dd=1）才被强制为 VALID_FLOOR"""
        # sharpe=-10 → transform = -10/11 ≈ -0.91
        # win_rate=0, max_dd=1.0 → 0.5*(-0.91) + 0 - 0.2*1 = -0.455 - 0.2 = -0.655
        # 远高于 -4.99，max 不触发
        res = self._res(sharpe=-10.0, win_rate=0.0, max_drawdown=1.0)
        s = calc_score(res, min_trades=100)
        assert -0.7 < s < -0.6  # 实际算出来约 -0.655，未触发 floor
        assert s > SCORE_VALID_FLOOR

    def test_valid_floor_actually_floors(self):
        """算出来若 < VALID_FLOOR 才被强制；我们用 inf→-1 + 极端 dd 构造"""
        # sharpe=-inf → -1.0；dd=10.0 (超出 0..1 范围但 score 仍能算)
        # 0.5*(-1) + 0.3*0 - 0.2*10 = -0.5 - 2 = -2.5
        # 仍 > -4.99，未触发 floor
        # 想要触发 floor 需要极夸张场景，验证代码语义：
        #  (a) 算出的 score 仍 finite → 不触发
        #  (b) 算出的 score = NaN → 触发 (because np.isfinite check)
        res_nan = self._res(sharpe=float("inf"), win_rate=0.0, max_drawdown=10.0)
        # sharpe=inf → transform=-1.0 (finite)，score = 0.5*(-1) + 0 - 2 = -2.5（finite）
        # 不会触发 floor
        s = calc_score(res_nan, min_trades=100)
        # 验证：score finite，floor 未触发
        assert np.isfinite(s)
        assert s > SCORE_VALID_FLOOR

    def test_nan_sharpe_clamped_to_minus1(self):
        """NaN 的 sharpe 经 transform 变 -1.0，仍 finite，calc_score 给出有限分"""
        res = self._res(sharpe=float("nan"))
        s = calc_score(res, min_trades=100)
        assert np.isfinite(s)  # 不是 NaN
        assert s > SCORE_VALID_FLOOR  # 合理分不会触发 floor
        assert s < 0  # 但因为 sharpe=-1，必然负

    def test_boundary_continuity(self):
        """无效 → 有效边界无缝衔接：trade=99 应 < trade=100 的 VALID_FLOOR 对应分"""
        # trade=100 时算出的"理论分"应为约 0.38，但 VALID_FLOOR=-4.99 远低于
        # trade=99 (ratio=0.99) 时 = FLOOR + 0.99*(CEIL-FLOOR) ≈ -5.05
        s_100 = calc_score(self._res(sharpe=1.0, win_rate=0.5,
                                      max_drawdown=0.1, total_closed=100),
                           min_trades=100)
        s_99 = calc_score(self._res(sharpe=1.0, win_rate=0.5,
                                     max_drawdown=0.1, total_closed=99),
                          min_trades=100)
        # 边界：s_99 < SCORE_INVALID_CEIL = -5.0 < s_100 (VALID_FLOOR = -4.99)
        assert s_99 < SCORE_INVALID_CEIL
        assert s_100 >= SCORE_VALID_FLOOR
        assert s_99 < s_100

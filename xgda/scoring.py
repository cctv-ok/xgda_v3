"""统一打分入口：网格 / GA / 样本外共用。"""
import numpy as np
from .config import (
    SCORE_W_SHARPE, SCORE_W_WINRATE, SCORE_W_DRAWDOWN,
    SCORE_INVALID_FLOOR, SCORE_INVALID_CEIL, SCORE_VALID_FLOOR,
)


def _sharpe_transform(sharpe: float) -> float:
    """有界化 Sharpe：sharpe/(1+|sharpe|) ∈ (-1, 1)。

    优势：替代 tanh 在 |sharpe|>2 后饱和，符号与单调性保留。
    """
    if not np.isfinite(sharpe):
        return -1.0
    return sharpe / (1.0 + abs(sharpe))


def calc_score(res: dict, min_trades: int = 100, use_gradient: bool = True) -> float:
    """统一打分函数。

    Args:
        res: run_backtest 返回的 dict
             （含 sharpe / win_rate / max_drawdown / total_closed / ...）
        min_trades: 最低有效交易笔数
        use_gradient: True 时按接近门槛程度给线性梯度

    Returns:
        float 分值（无效个体 ∈ [FLOOR, CEIL]，有效个体下限 VALID_FLOOR）

    Notes:
        * 无效个体：trade < min_trades → 梯度或直返下限
        * 有效个体：score = 0.5*_sharpe + 0.3*winrate - 0.2*maxdd
        * SCORE_VALID_FLOOR = -4.99 恰好跨过 SCORE_INVALID_CEIL = -5.0，
          保证网格/GA 排序时不会出现"达标个体反不如差个体"的塌陷。
    """
    n = res["total_closed"]
    if n < min_trades:
        if use_gradient and min_trades > 0:
            ratio = min(max(n / min_trades, 0.0), 1.0)
            return float(
                SCORE_INVALID_FLOOR
                + (SCORE_INVALID_CEIL - SCORE_INVALID_FLOOR) * ratio
            )
        return float(SCORE_INVALID_FLOOR)

    score = (
        SCORE_W_SHARPE * _sharpe_transform(res["sharpe"])
        + SCORE_W_WINRATE * res["win_rate"]
        - SCORE_W_DRAWDOWN * res["max_drawdown"]
    )
    if not np.isfinite(score):
        score = SCORE_VALID_FLOOR
    return float(max(score, SCORE_VALID_FLOOR))

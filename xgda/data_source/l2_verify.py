"""9:25 选股后的 L2 实时盘口校验。

核心作用
--------
xgda_signal 在盘中 9:25 已产生候选 watchlist（基于昨日 close + 今日参数空间）。
但盘中 9:25 集合竞价刚开，这时拿到的"信号"实际是隔夜预测。
本模块提供**二次筛选**：把候选扔给 L2 实时盘口，按集合竞价匹配结果
量化每只候选的可执行性，输出加权后的最终 watchlist。

排序逻辑
--------
`scoring_for_quote(quote, xg_score)` 综合 4 个因子：
  1. 集合竞价匹配量 > 0（说明有人接盘）
  2. bid_ask_ratio > 1.0（买盘 > 卖盘，多头占优）
  3. spread 较小（流动性好）
  4. xg_signal_score ≥ 0（基础信号分非负）

得分 = 0.35 * match_signal + 0.25 * ba_ratio + 0.20 * liq_score + 0.20 * xg_score

不可用（unknown=True）则降级为 xg_score 单独得分，不阻塞流程。

输入 / 输出
----------
输入：candidate_codes (List[str]) + xg_scores (Dict[code, float]) + L2QuoteFetcher
输出：List[(code, final_score, l2_quote)]，按 final_score 降序
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from xgda.data_source.tdx_socket import (
    L2Quote,
    L2QuoteFetcher,
    NoopL2Fetcher,
    is_call_auction_now,
)


@dataclass
class VerifiedCandidate:
    code: str
    final_score: float
    xg_score: float
    l2_score: float
    quote: L2Quote
    notes: List[str] = field(default_factory=list)


def _match_signal_score(q: L2Quote) -> float:
    """集合竞价匹配量评分（0-1）。

    量 ≤ 0 → 0
    量在 (0, 1万股] → 线性映射到 0.3
    量在 (1万, 50万股] → 0.3-0.7
    量 > 50万股 → 0.7-1.0（log 缩放）
    """
    mv = q.call_auction_match_volume
    if not mv or mv <= 0:
        return 0.0
    if mv <= 10000:
        return 0.3 * (mv / 10000.0)
    if mv <= 500_000:
        return 0.3 + 0.4 * ((mv - 10000) / (500_000 - 10000))
    # log scale: 50万→0.7, 500万→0.85, 5000万→0.95, 5亿→1.0
    return min(1.0, 0.7 + 0.3 * math.log10(mv / 500_000) / 3.0)


def _ba_ratio_score(q: L2Quote) -> float:
    """买卖盘比评分（0-1）。
    ratio < 0.5 → 0
    0.5-1.0 → 0.3-0.5
    1.0-2.0 → 0.5-0.8
    > 2.0 → 0.8-1.0
    """
    r = q.bid_ask_ratio()
    if r is None or r <= 0:
        return 0.0
    if r <= 0.5:
        return 0.3 * (r / 0.5)
    if r <= 1.0:
        return 0.3 + 0.2 * ((r - 0.5) / 0.5)
    if r <= 2.0:
        return 0.5 + 0.3 * ((r - 1.0) / 1.0)
    return min(1.0, 0.8 + 0.2 * math.log10(r / 2.0) / 3.0)


def _liquidity_score(q: L2Quote) -> float:
    """流动性评分（0-1）。

    用 spread 与 bid1 量衡量：
    spread = (ask1-bid1)/mid_price
    spread ≤ 0.1% → 1.0
    spread ≥ 1.0% → 0.0
    区间内线性
    """
    if q.bid1_price is None or q.ask1_price is None:
        return 0.0
    if q.bid1_price <= 0 or q.ask1_price <= 0:
        return 0.0
    mid = (q.ask1_price + q.bid1_price) / 2.0
    spread_pct = (q.ask1_price - q.bid1_price) / mid
    if spread_pct <= 0.001:
        s = 1.0
    elif spread_pct >= 0.01:
        s = 0.0
    else:
        s = (0.01 - spread_pct) / (0.01 - 0.001)
    # bid1 量 < 1000手 → 折半
    bv = q.bid1_volume or 0
    if bv < 1000:
        s *= 0.5
    return s


def l2_score(quote: L2Quote) -> Tuple[float, List[str]]:
    """综合 L2 评分（0-1）。

    Returns:
        (score, notes)
        notes 用于调试/排错时打印。
    """
    notes: List[str] = []

    if quote.is_suspended:
        notes.append("停牌")
        return 0.0, notes

    if quote.unknown:
        notes.append("L2 不可用，降级为 XGDA 单独评分")
        return 0.0, notes

    m = _match_signal_score(quote)
    r = _ba_ratio_score(quote)
    l = _liquidity_score(quote)
    score = 0.50 * m + 0.30 * r + 0.20 * l
    score = max(0.0, min(1.0, score))

    notes.append(f"竞价匹配={m:.2f} b/a={r:.2f} 流动性={l:.2f}")
    return score, notes


def combine_score(xg_score: float, l2: float,
                  weights: Tuple[float, float] = (0.6, 0.4)) -> float:
    """XGDA 信号分 + L2 实时分 加权合并。"""
    w_xg, w_l2 = weights
    return max(0.0, min(1.0, w_xg * xg_score + w_l2 * l2))


def verify_with_l2(candidate_codes: List[str],
                   xg_scores: Dict[str, float],
                   fetcher: Optional[L2QuoteFetcher] = None,
                   weights: Tuple[float, float] = (0.6, 0.4),
                   ) -> List[VerifiedCandidate]:
    """对候选 watchlist 拉 L2 实时盘口并打分。

    Args:
        candidate_codes: XGDA 信号选出的候选代码
        xg_scores: code -> 归一化的 XGDA 打分 (0-1)
        fetcher: L2 抓取器；None → NoopL2Fetcher
        weights: (xg权重, l2权重)，和为 1.0

    Returns:
        按 final_score 降序的列表
    """
    fetcher = fetcher or NoopL2Fetcher()
    results: List[VerifiedCandidate] = []

    # 单连接批量拉（fetcher 内部已实现批量）
    quotes = fetcher.fetch_many(candidate_codes)
    quote_map = {q.code: q for q in quotes}

    for code in candidate_codes:
        q = quote_map.get(code, L2Quote(code=code, unknown=True))
        xg_s = xg_scores.get(code, 0.0)
        l2_s, notes = l2_score(q)
        final = combine_score(xg_s, l2_s, weights)
        if q.is_call_auction:
            notes.append("9:15-9:25 集合竞价时段")
        elif is_call_auction_now():
            notes.append("当前为集合竞价但 quote 未标记（数据可能滞后）")

        results.append(VerifiedCandidate(
            code=code,
            final_score=final,
            xg_score=xg_s,
            l2_score=l2_s,
            quote=q,
            notes=notes,
        ))

    results.sort(key=lambda r: r.final_score, reverse=True)
    return results


def filter_top_n(results: List[VerifiedCandidate],
                 top_n: int = 5,
                 min_score: float = 0.0,
                 require_known: bool = False) -> List[VerifiedCandidate]:
    """从 verify 结果取 Top-N，可选加最低分门槛 / 强制要求 L2 数据已知。"""
    out = [r for r in results
           if r.final_score >= min_score
           and (not require_known or not r.quote.unknown)]
    return out[:top_n]


__all__ = [
    "VerifiedCandidate",
    "l2_score",
    "combine_score",
    "verify_with_l2",
    "filter_top_n",
]

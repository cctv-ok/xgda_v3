"""Backtrader 策略实现 (v3.0 → v3.1)

要点：
    * T-1 信号 → T 日开盘买（T+1 一致性）
    * pending_buy 超时（默认 3 根 bar）防涨跌停永久卡死
    * 估算价不再含魔数 0.005（已移交给 broker 层）
    * 估算委托大小按股数取整（≥100）
"""
import random
from datetime import date
import backtrader as bt

from .config import (
    HOLD_DAYS, STOP_LOSS_RATE, MAX_POS_COUNT, STRATEGY_SEED,
    SLIPPAGE,
)


class XgdaStrategy(bt.Strategy):
    """XGDA 选股策略。

    买卖规则：
        1. 持 HOLD_DAYS 个 bar 或触发止损 → 卖出
        2. 持 max_pos 个仓位
        3. 候选 = 昨日信号为 1 且当前无挂单 → 按随机种子乱序取 max_pos
        4. 资金 = cash / 候选数 * 0.95（保留 5% 缓冲）
        5. 委托 size = int((per_cash / estimate_px) / 100) * 100（取整到 100 股）
        6. 挂单未成交超过 pending_timeout_bars → 放弃
    """
    params = (
        ("signal_df", None),
        ("hold_days", HOLD_DAYS),
        ("stop_loss", STOP_LOSS_RATE),
        ("max_pos", MAX_POS_COUNT),
        ("seed", STRATEGY_SEED),
        ("global_date_idx", None),
        ("global_date_list", None),
        ("pending_timeout_bars", 3),
    )

    def __init__(self):
        self.signal_df = self.p.signal_df
        self.hold_days_map = {}
        self.pending_close = {}
        self.pending_buy = {}
        self.pending_buy_bars = {}      # code -> 已挂 bar 数
        self._seed = self.p.seed
        self._bar_count = 0
        self.global_date_idx = self.p.global_date_idx or {}
        self.global_date_list = self.p.global_date_list or []
        # 预构建 code -> {date: xg}
        self.signal_dict = {}
        for code, subdf in self.signal_df.groupby("code"):
            self.signal_dict[code] = dict(
                zip(subdf["datetime_date"], subdf["xg"])
            )

    def notify_order(self, order):
        code = order.data.code
        if order.status == order.Completed:
            if order.isbuy():
                self.hold_days_map[code] = 0
            else:
                self.hold_days_map.pop(code, None)
            self.pending_buy[code] = False
            self.pending_buy_bars.pop(code, None)
            self.pending_close[code] = False
        elif order.status in (order.Canceled, order.Margin, order.Rejected):
            self.pending_buy[code] = False
            self.pending_buy_bars.pop(code, None)
            self.pending_close[code] = False

    def _prev_trading_date(self, cur_dt):
        g_idx = self.global_date_idx.get(cur_dt)
        if g_idx is None or g_idx == 0:
            return None
        return self.global_date_list[g_idx - 1]

    def next(self):
        self._bar_count += 1
        current_pos_num = sum(
            1 for d in self.datas if self.getposition(d).size > 0
        )
        buy_candidates = []

        for d in self.datas:
            code = d.code
            dt: date = d.datetime.date()
            pos = self.getposition(d)

            # ---- 已有持仓：止损 / 到期 ----
            if pos.size > 0:
                if self.pending_close.get(code, False):
                    continue
                self.hold_days_map[code] = self.hold_days_map.get(code, 0) + 1
                if d.close[0] <= pos.price * (1 - self.p.stop_loss):
                    self.close(data=d)
                    self.pending_close[code] = True
                    continue
                if self.hold_days_map[code] >= self.p.hold_days:
                    self.close(data=d)
                    self.pending_close[code] = True
                continue

            # ---- 空仓：检查挂单状态 ----
            if self.pending_buy.get(code, False):
                self.pending_buy_bars[code] = (
                    self.pending_buy_bars.get(code, 0) + 1
                )
                if self.pending_buy_bars[code] >= self.p.pending_timeout_bars:
                    self.pending_buy[code] = False
                    self.pending_buy_bars.pop(code, None)
                else:
                    continue

            # ---- 空仓：检查 T-1 日信号 ----
            prev_dt = self._prev_trading_date(dt)
            if prev_dt is None:
                continue
            if self.signal_dict.get(code, {}).get(prev_dt, 0) != 1:
                continue
            buy_candidates.append(d)

        remain_slots = self.p.max_pos - current_pos_num
        if remain_slots <= 0 or not buy_candidates:
            return

        rng = random.Random(self._seed + self._bar_count)
        rng.shuffle(buy_candidates)
        selected = buy_candidates[:remain_slots]

        cash = self.broker.getcash()
        per_cash = cash / max(len(selected), 1) * 0.95
        for d in selected:
            code = d.code
            # 估算成交价：滑点已在 broker 层扣除，这里只做股数保守估算
            estimate_px = d.close[0] * (1 + SLIPPAGE)
            size = int(per_cash / estimate_px / 100) * 100
            if size >= 100:
                self.buy(data=d, size=size)
                self.pending_buy[code] = True
                self.pending_buy_bars[code] = 0

"""回测入口 v3.1

修复点：
    * Sharpe riskfreerate 显式按日频折算（年化2% → 0.02/252）
    * 胜率分母改 total_closed（v3.0 修复）
    * Calmar 无回撤时不再人为放大
"""
import numpy as np
import pandas as pd
import backtrader as bt

from .config import (
    COMMISSION, SLIPPAGE, INIT_CASH, STRATEGY_SEED,
    RISK_FREE_ANNUAL, TRADING_DAYS,
    MAX_POS_COUNT, HOLD_DAYS, STOP_LOSS_RATE,
    PARAM_SPACE,
)
from .signal import xgda_signal
from .strategy import XgdaStrategy


def run_backtest(params: dict, all_df: pd.DataFrame) -> dict:
    """单次回测。日历由传入 all_df 自行构建，避免 train/test 切分后错位。"""
    empty = {
        "sharpe": 0.0, "win_rate": 0.0, "max_drawdown": 1.0,
        "calmar": -1.0, "total_closed": 0, "final_value": INIT_CASH,
    }
    if len(all_df) == 0:
        return empty

    xg_series = xgda_signal(all_df, params)
    sig_df = all_df[["code", "datetime_date"]].copy()
    sig_df["xg"] = xg_series.values

    trade_dates = sorted(all_df["datetime_date"].unique())
    date_idx = {dt: i for i, dt in enumerate(trade_dates)}

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(INIT_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)
    cerebro.broker.set_slippage_perc(SLIPPAGE)

    for code, df_stock in all_df.groupby("code", sort=False):
        bt_data = bt.feeds.PandasData(
            dataname=df_stock.reset_index(drop=True),
            datetime="datetime",
            open="open", high="high", low="low",
            close="close", volume="volume",
        )
        bt_data.code = code
        cerebro.adddata(bt_data)

    # 策略参数透传（修复 C 项：仅当 strategy_param_key 非 None 时才传）
    strat_kwargs = dict(
        signal_df=sig_df,
        global_date_idx=date_idx,
        global_date_list=trade_dates,
        hold_days=HOLD_DAYS,
        stop_loss=STOP_LOSS_RATE,
        max_pos=MAX_POS_COUNT,
        seed=STRATEGY_SEED,
    )
    for (name, _, _, _, _, skey) in PARAM_SPACE:
        if skey is not None and skey in params:
            strat_kwargs[skey] = params[name]
    cerebro.addstrategy(XgdaStrategy, **strat_kwargs)

    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(
        bt.analyzers.SharpeRatio, _name="sharpe",
        riskfreerate=RISK_FREE_ANNUAL / TRADING_DAYS,
        timeframe=bt.TimeFrame.Days,
        factor=TRADING_DAYS, annualize=True,
    )
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="timereturn")

    result = cerebro.run()
    strat = result[0]

    sharpe_raw = strat.analyzers.sharpe.get_analysis().get("sharperatio", None)
    sharpe = 0.0 if (sharpe_raw is None or not np.isfinite(sharpe_raw)) \
        else float(sharpe_raw)

    dd = strat.analyzers.drawdown.get_analysis()
    max_dd = dd.get("max", {}).get("drawdown", 0.0) / 100.0
    if not np.isfinite(max_dd) or max_dd < 0:
        max_dd = 1.0

    trade_ana = strat.analyzers.trades.get_analysis()
    total_closed = trade_ana.get("total", {}).get("closed", 0)
    won_total = trade_ana.get("won", {}).get("total", 0)
    lost_total = trade_ana.get("lost", {}).get("total", 0)
    # ★ 关键：分母用 total_closed，纳入 even
    win_rate = (won_total / total_closed) if total_closed > 0 else 0.0

    final_value = cerebro.broker.getvalue()
    total_return = final_value / INIT_CASH - 1.0
    if max_dd > 1e-6:
        calmar = total_return / max_dd
    else:
        calmar = float(total_return)

    return {
        "sharpe": float(sharpe),
        "win_rate": float(win_rate),
        "max_drawdown": float(max_dd),
        "calmar": float(calmar),
        "total_closed": int(total_closed),
        "final_value": float(final_value),
        "_won_total": won_total,
        "_lost_total": lost_total,
    }

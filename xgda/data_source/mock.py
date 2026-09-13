"""Mock 数据 fixture（程序生成，零外部依赖）

用途：
    * 单元测试 (test_smoke.py / test_signal.py)
    * 冒烟测试 (run_smoke.py)
    * CI / 离线调试

设计：
    * n_stocks 只 mock 股票，n_days 个交易日
    * 价格用几何布朗运动，amount 用 close * volume 模拟
    * 注入少量 ST / 688 标的，让 base_ok 过滤有效
"""
import numpy as np
import pandas as pd

from .factors import build_st_flags, build_circ_value_z


def load_mock(n_stocks: int = 5, n_days: int = 60,
              seed: int = 42) -> pd.DataFrame:
    """生成 mock 数据集。

    Args:
        n_stocks: 股票数量
        n_days: 交易日数量
        seed: 随机种子（可重现）

    Returns:
        pd.DataFrame: 符合 XGDA 期望 schema
    """
    rng = np.random.default_rng(seed)
    # 6 位代码：前 1-2 位真实风格
    code_prefixes = ["600", "601", "000", "002", "300"]
    codes = []
    i = 0
    while len(codes) < n_stocks:
        prefix = code_prefixes[i % len(code_prefixes)]
        suffix = f"{rng.integers(100, 999):03d}"
        code = (prefix + suffix)[:6].ljust(6, "0")
        if code not in codes:
            codes.append(code)
        i += 1

    # 时间轴：n_days 个连续工作日，从 2025-01-02 起
    dates = pd.bdate_range("2025-01-02", periods=n_days).date

    records = []
    for code in codes:
        price0 = float(rng.uniform(10, 100))
        # 几何布朗运动
        rets = rng.normal(0.0005, 0.02, size=n_days)
        closes = price0 * np.exp(np.cumsum(rets))
        opens = closes * (1 + rng.normal(0, 0.005, size=n_days))
        highs = closes * (1 + np.abs(rng.normal(0, 0.008, size=n_days)))
        lows = closes * (1 - np.abs(rng.normal(0, 0.008, size=n_days)))
        volumes = rng.integers(1_000_000, 10_000_000, size=n_days)
        amounts = closes * volumes

        for j, d in enumerate(dates):
            records.append({
                "code": code,
                "datetime": pd.Timestamp(d),
                "open": float(opens[j]),
                "high": float(highs[j]),
                "low": float(lows[j]),
                "close": float(closes[j]),
                "volume": int(volumes[j]),
                "amount": float(amounts[j]),
                "st_num": 0,
            })

    df = pd.DataFrame(records)
    df.sort_values(["code", "datetime"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    # 派生因子
    df["datetime_date"] = df["datetime"].dt.date
    build_st_flags(df)
    build_circ_value_z(df, output_scale="yuan")
    return df

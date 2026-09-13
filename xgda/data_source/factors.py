"""因子计算工具（在标准 OHLCV 基础上派生 XGDA 所需字段）

设计约束：
    XGDA 核心因子是「流通市值 Z」（circ_value_z）。
    tdx7 本地 CSV **没有**流通市值字段，只有成交额。
    因此我们用「最近 N 日平均成交额的 Z 分数」作为代理：
        circ_value_z = (avg_amount - μ) / σ
    解释：成交额活跃度 ≈ 关注度 ≈ 市值活跃度（在 A 股有强相关性）
    极端行情下相关性会偏差，但对 z_min/z_max 自适应已足够鲁棒。

    当 cctv MARKET 项目集成完毕并提供真实流通市值列时，本模块可一键替换
    实现（接口不变）。
"""
import numpy as np
import pandas as pd


def _to_num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def build_st_flags(df: pd.DataFrame, code_col: str = "code") -> None:
    """派生 code_ok / st_ok / base_ok（in-place）。

    Args:
        df: 需含 code 列；若已有 st 列则用之，否则置 0
    """
    df["code"] = df[code_col].astype(str).str.zfill(6)
    # 排除 688/8/4/9 北交所/科创板/B 股
    df["code_ok"] = ~df["code"].str.startswith(("688", "8", "4", "9"))
    if "st" in df.columns:
        df["st_num"] = _to_num(df["st"]).fillna(0)
    elif "st_num" not in df.columns:
        df["st_num"] = 0
    df["st_ok"] = df["st_num"] == 0
    df["base_ok"] = df["code_ok"] & df["st_ok"]


def build_circ_value_z(df: pd.DataFrame, window: int = 20,
                       use_col: str = None,
                       output_scale: str = "raw") -> None:
    """派生 circ_value_z（in-place）。

    优先使用 `use_col` 列（cctv MARKET 扩展格式里的真实流通市值），
    缺省时退化为 amount Z 分数（tdx7 本地格式）。

    Args:
        df: 需含 code/datetime/amount 列
        window: 滚动窗口（日）
        use_col: 真实流通市值列名（如 'circ_value' / 'free_cap'），None 时降级
        output_scale: "raw" → 保留 Z 分数（tdx7 真实模式用）
                      "yuan" → 线性缩放到「亿元」量级（mock + z_min/z_max 配套用）

    修复：PARAM_SPACE 默认 [6, 80] 是亿元单位，但 amount Z 分数范围 [-3, 3]。
        两套并行：真实模式用 raw，mock 测试用 yuan 缩放。
    """
    target_col = use_col if (use_col and use_col in df.columns) \
        else ("amount" if "amount" in df.columns else "volume")

    df["circ_value_raw"] = _to_num(df[target_col]).fillna(0)
    # min_periods=1 让冷启动（小数据量）也能出值；不影响大数据集（首日仅用首值）
    by_code = df.groupby("code", sort=False)["circ_value_raw"] \
        .transform(lambda s: s.rolling(window, min_periods=1).mean())
    valid = by_code.replace([np.inf, -np.inf], np.nan).dropna()
    if len(valid) == 0:
        df["circ_value_z"] = np.nan
        return
    raw_z = (by_code - float(valid.mean())) / float(valid.std())
    raw_z = raw_z.replace([np.inf, -np.inf], 0).fillna(0)

    if output_scale == "yuan":
        # 缩放到亿元量级（μ=50, σ=20），落在 [10, 100]
        mu, sigma = 50.0, 20.0
        df["circ_value_z"] = mu + sigma * raw_z
        df["circ_value_z"] = df["circ_value_z"].clip(lower=1.0, upper=200.0)
    else:
        df["circ_value_z"] = raw_z.replace([np.inf, -np.inf], np.nan)

"""XGDA 信号生成：流通市值 Z ∈ [z_min, z_max] 基础筛选。"""
import pandas as pd


def xgda_signal(df: pd.DataFrame, params: dict) -> pd.Series:
    """XGDA 信号函数。

    Args:
        df: 必须包含以下列（由 data_source.load_data 适配）：
            - base_ok (bool): 非 ST / 非 688/8/4/9 北交所
            - circ_value_z (float, 可 NaN): 流通市值 Z 分数
            - code, datetime, datetime_date
        params: {'z_min': int, 'z_max': int}

    Returns:
        pd.Series[int]: 1 当日入选，0 当日不入。
        信号基于当日数据；实盘应在 T+1 开盘执行（与 XgdaStrategy 配合）。

    修复 E 项：当 circ_value_z 全 NaN 时打印一次警告。
    """
    z_min = params["z_min"]
    z_max = params["z_max"]
    z = df["circ_value_z"]

    # 全 NaN 防御：通常发生在 data_source 未装载因子时
    if z.isna().all():
        print("[xgda_signal] ⚠️ circ_value_z 全 NaN，xg 信号列为空。"
              "请检查 data_source.build_circ_value_z() 链路。")

    cond_z = z.notna() & (z >= z_min) & (z <= z_max)
    return (df["base_ok"] & cond_z).astype(int)

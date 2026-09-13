"""通达信 D:\\tdx7 历史 CSV 适配器（v3.1 关键改进）

真实 tdx7 CSV 格式（中表表头，7 列）：
    日期,开盘,最高,最低,收盘,成交量,成交额

v3.0 XGDA 期望字段：
    code, datetime, datetime_date, open, high, low, close, volume,
    circ_value_z, st_num, code_ok, st_ok, base_ok

适配层职责：
    1. 文件名 6 位代码 → code 字段
    2. 中文表头 → 英文（构建映射）
    3. 类型转换（防 TypeError，v3.0 修复 2）
    4. code_ok / st_ok / base_ok 派生
    5. circ_value_z 缺省时计算代理因子（用成交额 Z 分数代替）
"""
import glob
import os
import time
import numpy as np
import pandas as pd

from ..config import DATA_PATH
from .factors import build_circ_value_z, build_st_flags


def _to_num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def load_tdx7(path: str = None) -> pd.DataFrame:
    """加载 D:\\tdx7 真实行情并适配为 XGDA 期望 schema。

    Args:
        path: tdx7 目录，默认 DATA_PATH

    Returns:
        pd.DataFrame: 全市场日线（已含 base_ok / circ_value_z）
    """
    path = path or DATA_PATH
    csv_files = sorted(glob.glob(os.path.join(path, "*.csv")))
    if not csv_files:
        raise FileNotFoundError(f"{path} 下无 .csv 文件，请检查路径")

    df_list = []
    t0 = time.time()
    skipped = 0
    for i, fp in enumerate(csv_files, 1):
        try:
            df = pd.read_csv(fp, encoding="utf-8-sig")
        except Exception as e:
            skipped += 1
            continue

        # tdx7 文件名是 6 位代码
        code = os.path.basename(fp).replace(".csv", "")
        df["code"] = code
        # 中文表头 → 期望列名
        rename_map = {"日期": "datetime", "开盘": "open", "最高": "high",
                      "最低": "low", "收盘": "close",
                      "成交量": "volume", "成交额": "amount"}
        df.rename(columns=rename_map, inplace=True)
        df_list.append(df)

        if i % 500 == 0 or i == len(csv_files):
            print(f"[tdx7_load] {i}/{len(csv_files)} "
                  f"耗时 {time.time()-t0:.1f}s")

    if not df_list:
        raise RuntimeError(f"{path} 下所有 csv 均无法读取（skipped={skipped}）")

    all_df = pd.concat(df_list, ignore_index=True)

    # 数值清洗（v3.0 修复 2）
    all_df["code"] = all_df["code"].astype(str).str.zfill(6)
    all_df["datetime"] = pd.to_datetime(all_df["datetime"], errors="coerce")
    all_df.dropna(subset=["datetime", "close"], inplace=True)
    all_df.sort_values(["code", "datetime"], inplace=True)
    all_df.reset_index(drop=True, inplace=True)

    for col in ["open", "high", "low", "close", "volume", "amount"]:
        if col in all_df.columns:
            all_df[col] = _to_num(all_df[col])

    # 列规整：XGDA 必需列
    if "volume" not in all_df.columns and "amount" in all_df.columns:
        # volume 缺失：用 amount 作 proxy
        all_df["volume"] = all_df["amount"]

    # 因子派生
    all_df["datetime_date"] = all_df["datetime"].dt.date
    build_st_flags(all_df)        # code_ok / st_ok / base_ok
    build_circ_value_z(all_df)    # circ_value_z（缺流通市值时用 amount Z 替代）

    print(f"[tdx7_load] ✓ 完成：{len(all_df)} 行，"
          f"{all_df['code'].nunique()} 只股票，跳过 {skipped}")
    return all_df

"""cctv MARKET 项目 data/daily 扩展格式适配器（v3.3 新增）

cctv MARKET 项目的目录结构：
    C:\\Users\\Administrator\\Desktop\\MARKET\\data\\
        ├── daily/
        │   └── YYYYMMDD.csv            ← 每交易日 1 文件（11 列）
        └── liutong_shizhi_cache.csv     ← 真实流通市值缓存（code, liutong_shizhi_yi）

daily/YYYYMMDD.csv 列名：
    date, code, name, open, high, low, close, volume, amount,
    pct_chg, turnover_rate

与 tdx7 模式的关键差异：
    * date 字段在每一行内（不是文件名）→ 一文件可能含多只票
    * 自带 amount（成交额）和 turnover_rate → 直接可派生 Z 分数
    * 有 liutong_shizhi_cache.csv → 真实流通市值（亿元）做首选
"""
import glob
import os
import time
import pandas as pd

from ..config import DATA_PATH, EXTENDED_DAILY_DIR, EXTENDED_CACHE_FILE
from .factors import build_st_flags, build_circ_value_z, _to_num


def _load_liutong_shizhi(cache_path: str) -> pd.DataFrame:
    """读流通市值缓存，返回 [code, liutong_shizhi_yi] 两列。

    失败（不存在/格式错/空）→ 返回空 DataFrame，不抛异常。
    """
    if not cache_path or not os.path.exists(cache_path):
        return pd.DataFrame(columns=["code", "liutong_shizhi_yi"])
    try:
        df = pd.read_csv(cache_path, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame(columns=["code", "liutong_shizhi_yi"])
    if "code" not in df.columns or "liutong_shizhi_yi" not in df.columns:
        return pd.DataFrame(columns=["code", "liutong_shizhi_yi"])
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["liutong_shizhi_yi"] = _to_num(df["liutong_shizhi_yi"])
    return df[["code", "liutong_shizhi_yi"]].dropna()


def load_extended(daily_dir: str = None,
                  cache_file: str = None) -> pd.DataFrame:
    """加载 cctv MARKET 项目 data/daily + liutong_shizhi_cache。

    适配流程：
        1. glob data/daily/YYYYMMDD.csv，按文件并批读取
        2. 列重命名 + 类型转换（防 TypeError）
        3. 合并 liutong_shizhi_cache（left join on code）
        4. 派生 base_ok + circ_value_z（优先用真实市值）

    Args:
        daily_dir:  cctv MARKET data/daily 目录，None 时用 EXTENDED_DAILY_DIR
        cache_file: 流通市值缓存文件，None 时用 EXTENDED_CACHE_FILE

    Returns:
        pd.DataFrame: XGDA 统一 schema（与 tdx7 / mock 等价）
    """
    daily_dir = daily_dir or EXTENDED_DAILY_DIR
    cache_file = cache_file or EXTENDED_CACHE_FILE

    csv_files = sorted(glob.glob(os.path.join(daily_dir, "*.csv")))
    if not csv_files:
        raise FileNotFoundError(
            f"{daily_dir} 下无 .csv 文件，请检查路径或 cctv MARKET 是否已生成"
        )

    df_list = []
    t0 = time.time()
    skipped = 0
    for i, fp in enumerate(csv_files, 1):
        try:
            df = pd.read_csv(fp, encoding="utf-8-sig",
                             dtype={"code": str})
        except Exception as e:
            skipped += 1
            print(f"[extended_load] 跳过 {os.path.basename(fp)}: {e}")
            continue
        df_list.append(df)
        if i % 20 == 0 or i == len(csv_files):
            print(f"[extended_load] {i}/{len(csv_files)} "
                  f"耗时 {time.time()-t0:.1f}s")

    if not df_list:
        raise RuntimeError(f"{daily_dir} 下所有 csv 均无法读取")

    all_df = pd.concat(df_list, ignore_index=True)

    # ---- 列重命名 + 类型转换 ----
    rename_map = {
        "date": "datetime",
        "open": "open", "high": "high", "low": "low", "close": "close",
        "volume": "volume", "amount": "amount",
        "pct_chg": "pct_chg", "turnover_rate": "turnover_rate",
    }
    all_df.rename(columns=rename_map, inplace=True)
    all_df["code"] = all_df["code"].astype(str).str.zfill(6)
    all_df["datetime"] = pd.to_datetime(all_df["datetime"],
                                        format="%Y%m%d",
                                        errors="coerce")
    all_df.dropna(subset=["datetime", "close"], inplace=True)
    all_df.sort_values(["code", "datetime"], inplace=True)
    all_df.reset_index(drop=True, inplace=True)

    for col in ["open", "high", "low", "close", "volume", "amount",
                "pct_chg", "turnover_rate"]:
        if col in all_df.columns:
            all_df[col] = _to_num(all_df[col])

    # ---- 合并流通市值缓存（left join）----
    cap_df = _load_liutong_shizhi(cache_file)
    if len(cap_df) > 0:
        all_df = all_df.merge(cap_df, on="code", how="left")
    else:
        all_df["liutong_shizhi_yi"] = float("nan")

    n_with_real = int(all_df["liutong_shizhi_yi"].notna().sum())
    print(f"[extended_load] 流通市值缓存命中: {n_with_real}/"
          f"{len(all_df)} 行 ({n_with_real/len(all_df):.1%})")

    # ---- 因子派生 ----
    all_df["datetime_date"] = all_df["datetime"].dt.date
    build_st_flags(all_df)

    if n_with_real > 0:
        # 真实流通市值优先：直接用亿元值；未命中者用 amount Z 分数
        build_circ_value_z(all_df, output_scale="raw")  # amount_z 兜底
        real_mask = all_df["liutong_shizhi_yi"].notna()
        all_df.loc[real_mask, "circ_value_z"] = \
            all_df.loc[real_mask, "liutong_shizhi_yi"]
    else:
        # 无真实市值 → 全降级为 amount Z 分数
        build_circ_value_z(all_df, output_scale="raw")

    print(f"[extended_load] ✓ 完成: {len(all_df)} 行, "
          f"{all_df['code'].nunique()} 只票, "
          f"日期 {all_df['datetime_date'].min()} ~ "
          f"{all_df['datetime_date'].max()}, 跳过 {skipped}")
    return all_df
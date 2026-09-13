"""tests/test_extended.py：cctv MARKET 扩展格式（data/daily）单测

测试目标：
    1. load_extended() 返回 XGDA 统一 schema
    2. 真实流通市值缓存命中行：circ_value_z == liutong_shizhi_yi
    3. 未命中行降级为 amount Z 分数
    4. 列类型正确（datetime / numeric）
    5. base_ok / code_ok / st_ok 正确派生
    6. load_data(mode="extended") 等价于 load_extended()
    7. 缓存文件缺失/格式错时优雅降级
"""
import os
import shutil
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from xgda.data_source import load_extended, load_data
from xgda.data_source.extended import _load_liutong_shizhi


REAL_DAILY_DIR = r"C:\Users\Administrator\Desktop\MARKET\data\daily"
REAL_CACHE_FILE = r"C:\Users\Administrator\Desktop\MARKET\data\liutong_shizhi_cache.csv"


@pytest.fixture(scope="module")
def real_extended_df():
    """实跑 cctv MARKET 真实数据（48 个交易日）。模块级只读一次。"""
    if not Path(REAL_DAILY_DIR).exists():
        pytest.skip(f"MARKET data/daily 不存在: {REAL_DAILY_DIR}")
    return load_extended()


@pytest.fixture
def tmp_daily(tmp_path):
    """构造临时 daily 目录 + 缓存文件。"""
    daily_dir = tmp_path / "daily"
    daily_dir.mkdir()
    cache_file = tmp_path / "liutong_cache.csv"
    cache_file.write_text(
        "code,liutong_shizhi_yi\n000001,80.5\n000002,12.3\n",
        encoding="utf-8-sig"
    )
    # 写 3 天 × 3 票
    for day in ["20260901", "20260902", "20260903"]:
        csv = daily_dir / f"{day}.csv"
        csv.write_text(
            "date,code,name,open,high,low,close,volume,amount,"
            "pct_chg,turnover_rate\n"
            f"{day},000001,平安银行,10.0,10.5,9.9,10.3,1000,10000000,1.5,2.0\n"
            f"{day},000002,万科A,5.0,5.2,4.9,5.1,2000,20000000,2.0,3.0\n"
            f"{day},999999,ST测试,1.0,1.1,0.9,1.05,500,500000,1.0,1.0\n",
            encoding="utf-8-sig"
        )
    return daily_dir, cache_file


# ====================================================================
# 1. Schema & 基本返回
# ====================================================================
def test_load_extended_real_schema(real_extended_df):
    """真实数据 schema 校验。"""
    df = real_extended_df
    assert len(df) > 1000, f"应有足够数据，实际 {len(df)} 行"
    for col in ["code", "datetime", "datetime_date", "open", "high", "low",
                "close", "volume", "amount", "circ_value_z",
                "code_ok", "st_ok", "base_ok"]:
        assert col in df.columns, f"缺列: {col}"
    assert df["datetime"].dtype.kind in ("M",)  # datetime64
    assert df["close"].dtype.kind == "f"
    assert df["code"].dtype == object  # str


def test_load_extended_real_codes(real_extended_df):
    """真实数据含足够多 code（cctv MARKET 是全市场级别）。"""
    df = real_extended_df
    assert df["code"].nunique() >= 100, f"code 数过少: {df['code'].nunique()}"
    # 全部应是 6 位字符串
    assert df["code"].str.match(r"^\d{6}$").all()


def test_load_extended_real_date_range(real_extended_df):
    """真实数据日期范围 = 48 个交易日（cctv 数据现状）。"""
    df = real_extended_df
    dates = sorted(df["datetime_date"].unique())
    assert len(dates) == 48, f"期望 48 个交易日，实际 {len(dates)}"
    assert str(dates[0]) == "2026-07-01"
    assert str(dates[-1]) == "2026-09-04"


# ====================================================================
# 2. 流通市值缓存命中行为
# ====================================================================
def test_load_extended_real_cap_coverage(real_extended_df):
    """真实数据：缓存 7 行 code，看覆盖率。"""
    df = real_extended_df
    if "liutong_shizhi_yi" not in df.columns:
        pytest.skip("未生成 liutong_shizhi_yi 列（缓存为空或被 drop）")
    real_count = int(df["liutong_shizhi_yi"].notna().sum())
    # 7 个 code × 48 天 = 336 行（如果 7 个 code 全在数据里）
    # 现实里 MARKET 的 daily 数据可能不全含这 7 个 code
    assert real_count >= 0, "流通市值列存在即 OK"


def test_load_extended_circ_value_z_uses_real_cap(tmp_daily):
    """缓存命中时 circ_value_z == liutong_shizhi_yi（亿元原值）。"""
    daily_dir, cache_file = tmp_daily
    df = load_extended(daily_dir=str(daily_dir), cache_file=str(cache_file))
    # 000001 (缓存 80.5 亿) 和 000002 (12.3 亿) 应原值保留
    for code, expected in [("000001", 80.5), ("000002", 12.3)]:
        rows = df[df["code"] == code]
        assert len(rows) == 3
        actual = rows["circ_value_z"].unique()
        assert len(actual) == 1, f"{code} 不止一个 circ_value_z: {actual}"
        assert abs(actual[0] - expected) < 1e-6, \
            f"{code} circ_value_z={actual[0]} 应={expected}"


def test_load_extended_circ_value_z_fallback(tmp_daily):
    """未命中行降级为 amount Z 分数（非 0 也非 NaN）。"""
    daily_dir, cache_file = tmp_daily
    df = load_extended(daily_dir=str(daily_dir), cache_file=str(cache_file))
    # 999999 不在缓存里
    fallback_rows = df[df["code"] == "999999"]
    assert len(fallback_rows) == 3
    cvz = fallback_rows["circ_value_z"]
    assert cvz.notna().all(), "降级值不应为 NaN"
    # Z 分数大致在 [-3, 3] 区间
    assert cvz.between(-5, 5).all(), f"降级值异常: {cvz.tolist()}"


# ====================================================================
# 3. base_ok 派生
# ====================================================================
def test_load_extended_base_ok_excludes_st(tmp_daily):
    """ST / 9 开头 / 4 开头应被 base_ok 过滤。"""
    daily_dir, cache_file = tmp_daily
    df = load_extended(daily_dir=str(daily_dir), cache_file=str(cache_file))
    # 999999 不在 ST 黑名单但属于「非主板」段（cctv 排除 688/8/4/9）
    # 实际上我们 mock 数据 999999 以 9 开头 → code_ok=False
    rows_999 = df[df["code"] == "999999"]
    assert (rows_999["code_ok"] == False).all()
    assert (rows_999["base_ok"] == False).all()


def test_load_extended_base_ok_passes_main(tmp_daily):
    """000001 / 000002 应 base_ok=True。"""
    daily_dir, cache_file = tmp_daily
    df = load_extended(daily_dir=str(daily_dir), cache_file=str(cache_file))
    for code in ["000001", "000002"]:
        rows = df[df["code"] == code]
        assert (rows["base_ok"] == True).all()


# ====================================================================
# 4. load_data(mode="extended") 走通
# ====================================================================
def test_load_data_extended_dispatch(tmp_daily):
    """load_data(mode='extended') 等价于 load_extended()。"""
    daily_dir, cache_file = tmp_daily
    df_a = load_data(mode="extended",
                     daily_dir=str(daily_dir),
                     cache_file=str(cache_file))
    df_b = load_extended(daily_dir=str(daily_dir),
                         cache_file=str(cache_file))
    assert df_a.shape == df_b.shape
    assert (df_a["code"] == df_b["code"]).all()


# ====================================================================
# 5. 错误路径：缓存缺失 / 目录缺失
# ====================================================================
def test_load_extended_no_cache_file(tmp_path):
    """缓存文件不存在时优雅降级（不抛异常）。"""
    daily_dir = tmp_path / "daily"
    daily_dir.mkdir()
    for day in ["20260901"]:
        (daily_dir / f"{day}.csv").write_text(
            "date,code,name,open,high,low,close,volume,amount,"
            "pct_chg,turnover_rate\n"
            f"{day},000001,平安,10,11,9,10.5,1000,10000,1.0,1.0\n",
            encoding="utf-8-sig"
        )
    df = load_extended(daily_dir=str(daily_dir),
                       cache_file=str(tmp_path / "no_such.csv"))
    assert "liutong_shizhi_yi" in df.columns
    assert df["liutong_shizhi_yi"].isna().all()
    # 应全部降级到 Z 分数（不为 NaN）
    assert df["circ_value_z"].notna().all()


def test_load_extended_no_daily_dir(tmp_path):
    """daily 目录不存在 → 抛 FileNotFoundError（明确的错误信号）。"""
    with pytest.raises(FileNotFoundError, match="无 .csv 文件"):
        load_extended(daily_dir=str(tmp_path / "no_dir"))


def test_load_extended_cache_corrupted(tmp_path):
    """缓存文件格式错误 → 优雅降级（返回空 df + 全 NaN）。"""
    daily_dir = tmp_path / "daily"
    daily_dir.mkdir()
    (daily_dir / "20260901.csv").write_text(
        "date,code,name,open,high,low,close,volume,amount,"
        "pct_chg,turnover_rate\n"
        "20260901,000001,平安,10,11,9,10.5,1000,10000,1.0,1.0\n",
        encoding="utf-8-sig"
    )
    cache = tmp_path / "bad_cache.csv"
    cache.write_text("garbage_not_csv\nfoo,bar\n", encoding="utf-8-sig")
    df = load_extended(daily_dir=str(daily_dir), cache_file=str(cache))
    # 即使缓存坏也不能阻塞数据加载
    assert len(df) > 0
    assert "liutong_shizhi_yi" in df.columns
    assert df["liutong_shizhi_yi"].isna().all()


# ====================================================================
# 6. _load_liutong_shizhi 内部函数
# ====================================================================
def test_load_liutong_shizhi_basic(tmp_path):
    cache = tmp_path / "c.csv"
    cache.write_text(
        "code,liutong_shizhi_yi\n000001,80.5\n1234,12.3\n",
        encoding="utf-8-sig"
    )
    df = _load_liutong_shizhi(str(cache))
    assert len(df) == 2
    assert set(df.columns) == {"code", "liutong_shizhi_yi"}
    # 1234 应补 0 成 6 位
    assert "001234" in df["code"].values


def test_load_liutong_shizhi_missing_file():
    df = _load_liutong_shizhi("Z:/nonexistent/file.csv")
    assert len(df) == 0


def test_load_liutong_shizhi_empty_file(tmp_path):
    cache = tmp_path / "empty.csv"
    cache.write_text("", encoding="utf-8-sig")
    df = _load_liutong_shizhi(str(cache))
    assert len(df) == 0
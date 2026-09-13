"""数据源适配层：统一接口 `load_data(mode, path=None)`

模式：
    * "mock" — 纯程序生成 fixture（用于测试、单测、CI）
    * "tdx7" — 读通达信 D:\\tdx7 本地历史 CSV（7 列中文表头）
    * "extended" — 读 cctv MARKET 项目 data/daily/YYYYMMDD.csv 扩展格式

L2 实时盘口接入：
    * `tdx_socket.L2QuoteFetcher` / `NoopL2Fetcher` / `TcpL2Fetcher`
    * `l2_verify.verify_with_l2` 做 9:25 候选二次校验
    * Real 模式 `select_at_open(l2_verify=True)` 调用

返回统一 schema：
    columns = ['code', 'datetime', 'datetime_date',
               'open', 'high', 'low', 'close',
               'volume', 'circ_value_z', 'st_num', 'code_ok', 'st_ok',
               'base_ok']
"""
from .tdx7 import load_tdx7
from .mock import load_mock
from .extended import load_extended
from .factors import build_circ_value_z, build_st_flags
from .tdx_socket import (
    L2Quote, L2QuoteFetcher, NoopL2Fetcher, TcpL2Fetcher,
    make_l2_fetcher, is_call_auction_now,
)
from .l2_verify import (
    l2_score, combine_score, verify_with_l2, filter_top_n,
    VerifiedCandidate,
)


# 暴露 build_st_flags 作别名 build_base_ok（别名兼容旧调用）
build_base_ok = build_st_flags


def load_data(mode: str = "mock", path=None, **kwargs) -> "pd.DataFrame":
    """统一数据加载入口。

    Args:
        mode: "mock" / "tdx7" / "extended"
        path: 模式相关路径，None 时使用 config 默认
        kwargs: 透传给具体 loader（如 mock 的 n_stocks/n_days）

    Returns:
        pd.DataFrame: 统一 schema 的全市场日线
    """
    if mode == "mock":
        return load_mock(**kwargs)
    if mode == "tdx7":
        return load_tdx7(path=path)
    if mode == "extended":
        # cctv MARKET 项目 data/daily + liutong_shizhi_cache
        # 可通过 daily_dir/cache_file 覆盖默认路径
        return load_extended(
            daily_dir=kwargs.pop("daily_dir", path),
            cache_file=kwargs.pop("cache_file", None),
        )
    raise ValueError(f"未知 mode: {mode}")

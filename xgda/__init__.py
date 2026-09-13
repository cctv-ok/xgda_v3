"""XGDA — 流通市值 Z 自适应选股 (Z-marketcap Guided Adaptive) v3.2

三层架构：
    1. config + scoring + signal — 纯算法（无 IO）
    2. data_source — 数据接入 (mock / tdx7 / 扩展 + L2 实时盘口)
    3. real — 真实模式：盘中 9:25 选股调度（可叠加 L2 二次校验）

修复相对 v3.0：
    * G: walk_forward_validation 必须用 train_df（避免污染泛化测试）
    * B: 文档化「修改全局常量必清缓存」
    * C: PARAM_SPACE 第 6 项 (strategy_param_key) 注释约定
    * E: xgda_signal 全 NaN 时打印警告

v3.2 新增（XGDA + L2 实时盘口二层校验）：
    * `data_source.tdx_socket.L2QuoteFetcher` / `NoopL2Fetcher` / `TcpL2Fetcher`
    * `data_source.l2_verify.verify_with_l2` — 候选 + XGDA 分 → L2 加权排序
    * `real.select_at_open(l2_verify=True, l2_fetcher=...)` — 盘中启用 L2
"""
from .config import (
    PARAM_SPACE, POP_SIZE, GENERATIONS,
    COMMISSION, SLIPPAGE, HOLD_DAYS, STOP_LOSS_RATE,
    MAX_POS_COUNT, MIN_TRADE_COUNT, MIN_TRADE_COUNT_TEST,
    STRATEGY_SEED, INIT_CASH,
    RISK_FREE_ANNUAL, TRADING_DAYS,
    RUN_MODE, TEST_SPLIT_DATE, ENABLE_WALK_FORWARD,
    RESULT_CSV_TRAIN, RESULT_CSV_TEST, RESULT_CSV_WF,
    OVERFIT_GAP_THRESHOLD,
    SCORE_W_SHARPE, SCORE_W_WINRATE, SCORE_W_DRAWDOWN,
    SCORE_INVALID_FLOOR, SCORE_INVALID_CEIL, SCORE_VALID_FLOOR,
    DATA_PATH, TDX_SOCKET_HOST, TDX_SOCKET_PORT, WATCHLIST_BLK,
    L2_VERIFY_DEFAULT, L2_WEIGHTS_DEFAULT,
    clear_caches,
)
from .scoring import calc_score, _sharpe_transform
from .signal import xgda_signal
from .io_csv import write_result_csv
from .search import grid_search, genetic_search, walk_forward_validation
from .data_source import (
    load_data, load_mock, load_tdx7, build_circ_value_z, build_base_ok,
    L2Quote, L2QuoteFetcher, NoopL2Fetcher, TcpL2Fetcher,
    make_l2_fetcher, is_call_auction_now,
    l2_score, combine_score, verify_with_l2, filter_top_n,
    VerifiedCandidate,
)

__version__ = "3.2.0"

"""XGDA v3.1 全局配置（单一数据源）

⚠️ 重要约定（修复 B 项残留）
    修改 COMMISSION / SLIPPAGE / HOLD_DAYS / MAX_POS_COUNT / MIN_TRADE_COUNT /
    STRATEGY_SEED / INIT_CASH / RISK_FREE_ANNUAL / TRADING_DAYS 任一常量前，
    必须调用 `clear_caches()`（或重启进程），否则 _FIT_CACHE 会命中陈旧结果。
"""
# ---- 数据源 ----
DATA_PATH = r"D:\tdx7"               # 通达信本地历史 CSV 目录（6 列中文表头）
TDX_SOCKET_HOST = "127.0.0.1"        # 通达信 TCP 实时（来自 cctv 零依赖数据源 eltdx）
TDX_SOCKET_PORT = 0                  # TDX 客户端设置的端口（0 = 未配置，需在 TDX 中设定）
WATCHLIST_BLK = r"D:\tdx7\T0002\blocknew\333.blk"
VERBOSE = False

# ---- 参数搜索空间（唯一数据源）----
# 元组：(name, low, high, step, is_int, strategy_param_key)
#   * is_int=True  → 网格与 GA 个体均按 int 处理
#   * strategy_param_key=None       → 仅作信号参数（不传给 Backtrader）
#   * strategy_param_key="stop_loss" → 该参数也作为 XgdaStrategy 的 params 参数
#                                      扩展 stop_loss 等策略参数时启用
PARAM_SPACE = [
    ("z_min", 6,   30,   1, True,  None),
    ("z_max", 80,  120,  5, True,  None),
]

# ---- GA 配置 ----
POP_SIZE = 30
GENERATIONS = 40
MUTATION_RATE = 0.15
CROSSOVER_RATE = 0.8

# ---- 回测常量（会透传给 XgdaStrategy）----
COMMISSION = 0.0003
SLIPPAGE = 0.002
HOLD_DAYS = 5
STOP_LOSS_RATE = 0.05
MAX_POS_COUNT = 3
MIN_TRADE_COUNT = 100
MIN_TRADE_COUNT_TEST = 20
STRATEGY_SEED = 42
INIT_CASH = 100000
RISK_FREE_ANNUAL = 0.02             # 年化无风险利率（用于 Sharpe）
TRADING_DAYS = 252                  # 一年交易日数

# ---- 运行控制 ----
RUN_MODE = "grid"                   # "grid" / "ga"
TEST_SPLIT_DATE = "2023-01-01"      # 样本外切分
ENABLE_WALK_FORWARD = False         # 启用后做滚动验证

# ---- 输出文件 ----
RESULT_CSV_TRAIN = "xgda_result_train.csv"
RESULT_CSV_TEST = "xgda_result_test.csv"
RESULT_CSV_WF = "xgda_result_walkforward.csv"

# ---- TDX L2 实时盘口接入 ----
TDX_SOCKET_HOST = "127.0.0.1"   # 通达信客户端进程共享的 TCP 地址
TDX_SOCKET_PORT = 7709            # 通用 TDX TCP 端口（cctv 客户端实际配置为准）
WATCHLIST_BLK = "ZXG.blk"         # 选股结果可同步到该通达信自选股文件

# Real 模式 L2 验证默认开 / 关（select_at_open 仍可覆盖）
L2_VERIFY_DEFAULT = False
L2_WEIGHTS_DEFAULT = (0.6, 0.4)   # (XGDA 权重, L2 权重)

# ---- cctv MARKET 扩展数据源（v3.3 新增）----
EXTENDED_DAILY_DIR = r"C:\Users\Administrator\Desktop\MARKET\data\daily"
EXTENDED_CACHE_FILE = r"C:\Users\Administrator\Desktop\MARKET\data\liutong_shizhi_cache.csv"

# ---- 过拟合阈值 ----
OVERFIT_GAP_THRESHOLD = 0.3

# ---- 打分权重 ----
SCORE_W_SHARPE = 0.5
SCORE_W_WINRATE = 0.3
SCORE_W_DRAWDOWN = 0.2
SCORE_INVALID_FLOOR = -10.0
SCORE_INVALID_CEIL = -5.0
SCORE_VALID_FLOOR = -4.99           # 与无效个体上限对齐，消除边界断崖

# ---- 全局缓存 ----
_FIT_CACHE: dict = {}
_FP_CACHE: dict = {}


def clear_caches() -> None:
    """修改 COMMISSION/SLIPPAGE/HOLD_DAYS 等任一全局常量前必须调用。"""
    _FIT_CACHE.clear()
    _FP_CACHE.clear()

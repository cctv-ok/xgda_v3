# CHANGELOG — XGDA

## v3.1 (2026-09-13)

### 修复（相对 v3.0）
- **G**: `walk_forward_validation` 接受 `data` 参数，由调用方决定（默认传 `train_df`），避免泛化测试集被 WF 触及
- **B**: `xgda/config.py` 加文档注释："修改 COMMISSION/SLIPPAGE 等全局常量前必须 `clear_caches()`"
- **C**: `PARAM_SPACE` 第 6 项 `strategy_param_key` 注释约定
- **E**: `xgda_signal` 全 NaN 时打印警告

### 重大改进
- **数据源适配层** (`xgda/data_source/`):
  - `tdx7.py`：通达信 D:\tdx7 中文表头 → 期望 schema 完整适配
  - `mock.py`：程序生成 fixture（5-20 只 × 60-120 日）
  - `factors.py`：circ_value_z / base_ok / st_ok 派生
- **Real 模式** (`xgda/real.py`):
  - `select_at_open()`：9:25 盘中选股主入口
  - `DailyRunner`：时序调度（阻塞到 9:25 工作日）
  - 自动写 watchlist JSON + TDX 可粘贴 .txt

### 模块化重构
v3.0 单文件 (`xgda_v3.py`) → v3.1 拆分为 9 个职责明确模块：
- `config.py` / `scoring.py` / `signal.py` (纯算法)
- `strategy.py` / `backtest.py` (回测)
- `search.py` (grid + GA + WF)
- `plot.py` (4 个绘图)
- `data_source/` (数据适配层)
- `real.py` (盘中选股)

### 测试
- `test_scoring.py`：calc_score / _sharpe_transform 覆盖（边界、NaN、单调性）
- `test_signal.py`：xgda_signal 覆盖（base_ok 必选、NaN、边界包含）
- `test_smoke.py`：端到端 grid/GA 冒烟（mock 数据，2 代 GA + 4 组网格）

### 配置
- `requirements.txt`
- `.gitignore`
- `README.md` + `docs/CHANGELOG.md`

## v3.0 (2026-09-12)
原 v3.0 单文件版（保留为基线），包含 17 条更新日志。详见对话历史。

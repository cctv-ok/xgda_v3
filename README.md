# XGDA v3.3

> 流通市值 Z 自适应选股 (Z-marketcap Guided Adaptive) — 回测 + 参数自进化 + Real 模式

[![CI](https://github.com/cctv-ok/xgda_v3/actions/workflows/ci.yml/badge.svg)](https://github.com/cctv-ok/xgda_v3/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-136%20passed-brightgreen)](tests/)
[![Python](https://img.shields.io/badge/python-3.10-blue)](https://www.python.org/)

## 项目结构

```
xgda_v3/
├── README.md
├── CHANGELOG.md
├── requirements.txt
├── .gitignore
├── .github/
│   └── workflows/
│       └── ci.yml              # GitHub Actions CI（ubuntu + windows, py3.10）
├── xgda/                       # 主包
│   ├── __init__.py             # 公开 API 索引
│   ├── __main__.py             # CLI 入口 (python -m xgda)
│   ├── config.py               # 全局配置（单一数据源）
│   ├── scoring.py              # calc_score / _sharpe_transform
│   ├── signal.py               # xgda_signal
│   ├── strategy.py             # Backtrader Strategy
│   ├── backtest.py             # run_backtest
│   ├── io_csv.py               # write_result_csv
│   ├── search.py               # grid_search / genetic_search / walk_forward
│   ├── plot.py                 # 4 个绘图函数
│   ├── real.py                 # Real 模式：9:25 选股调度
│   └── data_source/            # 数据源适配层
│       ├── __init__.py         # 统一入口 load_data(mode)
│       ├── mock.py             # 程序生成 fixture
│       ├── tdx7.py             # 通达信 D:\tdx7 适配器（中文表头 → 期望 schema）
│       ├── tdx_socket.py       # L2 TCP fetcher（NoopL2Fetcher / TcpL2Fetcher）
│       ├── l2_verify.py        # 9:25 后 L2 实时盘口二次校验
│       ├── extended.py         # cctv MARKET data/daily 集成（含真实流通市值）
│       └── factors.py          # circ_value_z / base_ok / st_ok 派生
├── tests/                      # 单元测试 + 冒烟测试（136 个，100% 通过）
│   ├── conftest.py
│   ├── test_scoring.py         # 14
│   ├── test_signal.py          # 5
│   ├── test_smoke.py           # 4（端到端 backtest）
│   ├── test_l2_verify.py       # 38
│   ├── test_extended.py        # 15
│   └── test_xgda_schedule_py.py # 60（Python 调度器全逻辑）
├── scripts/
│   ├── run_smoke.py            # 离线冒烟
│   ├── run_real_live.py        # 9:25 盘中入口
│   ├── xgda-schedule-py.py     # stdlib-only 跨平台调度器（推荐生产用）
│   ├── xgda-dryrun.{bat,sh,ps1}     # 一键 dry-run
│   ├── xgda-live.{bat,sh,ps1}       # 一键真 9:25
│   └── xgda-schedule.{bat,ps1}      # Windows 任务计划包装（已弃用，被 .py 取代）
├── docs/
├── config/tdx_l2/
│   └── README.md               # nbcomte.dat 仅作参考（XGDA 不解析）
├── output/                     # 选股 JSON / 训练 CSV 输出
├── logs/
└── data/                       # tdx7 / extended 数据目录
```

## CI / CD

`push` / `pull_request` 自动触发 `.github/workflows/ci.yml`：

| Runner | Python | 目的 |
|---|---|---|
| `ubuntu-latest` | 3.10 | 主战场（CI matrix 第 1 个） |
| `windows-latest` | 3.10 | 验证生产平台兼容性（tdx_socket、路径处理） |

矩阵并行运行，约 5–7 分钟完成。依赖通过 `actions/setup-python` 的 `cache: pip` + `cache-dependency-path: requirements.txt` 缓存，重复运行秒级命中。

本地等价命令：

```bash
python -m pytest tests/ -v --tb=short
```

## 安装

```bash
# 建议用 Python 3.10（backtrader 不兼容 3.13）
pip install -r requirements.txt
```

## 快速开始

### 1. 跑全部测试

```bash
python -m pytest tests/ -v
# 期望：136 passed
```

### 2. 跑冒烟测试

```bash
python scripts/run_smoke.py
```

### 3. 训练（mock 数据）

```bash
python -m xgda --mode grid --data mock
```

输出：
- `xgda_result_train.csv` — 网格搜索结果
- `xgda_heatmap.png` / `xgda_heatmap_dual.png` — 热力图
- `xgda_stability.png` — 邻域稳定性
- `xgda_train_test_compare.png` — Train/Test 对比

### 4. 训练（真实 tdx7 数据）

```bash
python -m xgda --mode grid --data tdx7 --enable-wf
```

**前置**：通达信客户端在 `D:\tdx7` 维护行情（每日收盘后自动更新日线）

### 5. Real 模式（盘中 9:25 选股）

```bash
# 阻塞等到 09:25:01 后自动跑
python scripts/run_real_live.py

# 立即跑（覆盖时序检查）
python scripts/run_real_live.py --once

# Dry-run（mock 数据）
python scripts/run_real_live.py --dry
```

输出：`output/select_YYYY-MM-DD_HHMMSS.json` + `.txt`（可粘贴到 TDX 板块）

## Real 模式 + L2 实时盘口二次校验（v3.2 新增）

XGDA 9:25 选股可叠加一层 L2 实时盘口校验，在开盘后再筛一次：

```
09:25:00  集合竞价结束
09:25:01  ├─ XGDA 信号初筛（基于昨日历史）
          │  → 候选 ~N 只
          ├─ L2 实时盘口二次校验（可选）
          │  ├─ 集合竞价匹配量
          │  ├─ 十档买卖盘比
          │  └─ 流动性 spread
          ├─ xg_score × 0.6 + l2_score × 0.4 → final_score
          └─ 按 final_score 排序 → 入 max_pos 只
```

**接入步骤**：
1. 通达信客户端跑在 `D:\tdx7\TdxW.exe`，配套 `nbcomte.dat` 已就位
2. 启动通达信客户端，让其通过 `nbcomte.dat` 接入通用 L2 站点、共享 L2 行情给其它进程
3. cctv 在 `xgda/data_source/tdx_socket.py` 中**子类化 `TcpL2Fetcher`** 实现 `_send_recv_protocol()`（基于 pytdx / mootdx / eltdx）
4. 跑：`python scripts/run_real_live.py --once --l2-verify`

**注意事项**：
- XGDA **不解析、不接触 nbcomte.dat**——该文件由通达信客户端内部 `TdxAsioComm64.dll` 处理（合规边界）
- 默认 fetcher 是 `NoopL2Fetcher`，`--dry --l2-verify` 用 mock 跑通链路
- 真实接入的关键是 `_send_recv_protocol(code) -> dict`，cctv 自行实现协议层；XGDA 提供 TCP 连接管理 + 失败降级 + 字段解析

详见 `config/tdx_l2/README.md` 与 `tests/test_l2_verify.py`。

## 一键脚本（v3.3 新增 stdlib Python 调度器）

放在 `scripts/` 下，覆盖三种 shell + 跨平台 Python 调度器：

| 用途 | 文件 | 用法 |
|---|---|---|
| **dry-run** | `xgda-dryrun.bat` / `.sh` / `.ps1` | `scripts\xgda-dryrun.bat`（默认开 L2）<br>`scripts\xgda-dryrun.bat --no-l2`<br>`scripts\xgda-dryrun.bat --xg-weight 0.7` |
| **真 9:25** | `xgda-live.bat` / `.sh` / `.ps1` | `scripts\xgda-live.bat`（阻塞等到今日 09:25:01）<br>`scripts\xgda-live.bat --once`（立即跑） |
| **Python 调度器（推荐生产用）** | `xgda-schedule-py.py` | `python scripts/xgda-schedule-py.py`<br>支持 `--target HH:MM:SS`、`--no-l2`、`--xg-weight`、Ctrl-C 优雅退出 |

**为什么不用 Windows Task Scheduler**：在受限环境下 `Register-ScheduledTask` 静默返回 OK 但不实际注册；`xgda-schedule-py.py` 是 stdlib-only 跨平台方案（nohup 后台跑 / 或前台调试）。

实测：
- `.sh` 三种参数（默认 / `--no-l2` / `--xg-weight 0.7`）跑通，watchlist 落到 `output/`
- Python 调度器在 60 个单元测试下完整覆盖（parse_time / is_weekday / seconds_until_next / log / run_xgda_live / main / 端到端）

所有脚本自动探测 `D:\Codex_Work\xgda_v3\.venv\Scripts\python.exe`，无需手动配 PATH。

## 性能

- mock 5×60 网格搜索：约 3-8 秒
- tdx7 全市场 ~5000 只 × 2000 日 网格搜索 225 组：约 30-60 分钟（backtrader CPU-bound）
- GA 30 种群 × 40 代：约 3-8 倍于单次回测
- CI 单 runner 端到端（含 matplotlib 冷启动）：约 5-7 分钟

## 许可

仅技术代码演示，不构成投资建议。
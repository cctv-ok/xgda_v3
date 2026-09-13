"""XGDA v3.1 主入口

用法：
    python -m xgda                  # 训练 (grid + 样本外 + 可选 WF + 绘图)
    python -m xgda --real-dry       # Real 模式 dry-run（不读 TDX，验证链路）
    python -m xgda --real-once      # 立即跑一次 9:25 选股（覆盖时序检查）
"""
import os
import argparse
import random

import numpy as np
import pandas as pd

from .config import (
    RUN_MODE, TEST_SPLIT_DATE, ENABLE_WALK_FORWARD,
    RESULT_CSV_TRAIN, RESULT_CSV_TEST, RESULT_CSV_WF,
    OVERFIT_GAP_THRESHOLD,
    MIN_TRADE_COUNT, MIN_TRADE_COUNT_TEST, clear_caches,
)
from .data_source import load_data
from .scoring import calc_score
from .io_csv import write_result_csv
from .search import (
    grid_search, genetic_search, walk_forward_validation,
)
from .plot import (
    plot_grid_heatmap, plot_stability_analysis,
    plot_train_test_comparison, plot_walk_forward,
)


def train_pipeline(mode: str = RUN_MODE,
                   data_mode: str = "mock",
                   enable_wf: bool = ENABLE_WALK_FORWARD,
                   test_split: str = TEST_SPLIT_DATE) -> dict:
    """完整训练流水线：参数寻参 → 样本外测试 → WF（可选）→ 绘图。

    Args:
        mode: "grid" / "ga"
        data_mode: "mock" / "tdx7" — 数据源
        enable_wf: 是否启用 walk-forward（建议 False 直至数据量足够）
        test_split: 样本外切分点 YYYY-MM-DD

    Returns:
        dict: {'best_param', 'train_score', 'test_score', 'wf_results'}
    """
    random.seed(42); np.random.seed(42)
    for fp in [RESULT_CSV_TRAIN, RESULT_CSV_TEST, RESULT_CSV_WF]:
        if os.path.exists(fp):
            os.remove(fp)
    clear_caches()

    print(f"[main] 数据源: {data_mode}")
    all_data = load_data(mode=data_mode)
    print(f"[main] ✓ 数据装载: {len(all_data)} 行 / "
          f"{all_data['code'].nunique()} 只")

    all_data["datetime"] = pd.to_datetime(all_data["datetime"])
    train_df = all_data[all_data["datetime"] < test_split].copy()
    test_df = all_data[all_data["datetime"] >= test_split].copy()
    print(f"[main] Train: {len(train_df)} / Test: {len(test_df)}")

    if mode == "grid":
        best_param, best_score_train = grid_search(train_df, RESULT_CSV_TRAIN)
    else:
        best_param, best_score_train = genetic_search(train_df, RESULT_CSV_TRAIN)

    print("\n==== 样本外测试 ====")
    res_test = load_data.__module__ and _run_with_fresh_cache(
        best_param, test_df
    )
    score_test = calc_score(
        res_test, min_trades=MIN_TRADE_COUNT_TEST, use_gradient=True
    )
    write_result_csv(RESULT_CSV_TEST, best_param, score_test,
                     res_test, mode="test", tag="test")

    gap = abs(best_score_train - score_test)
    print(f"Train: {best_score_train:.4f} | Test: {score_test:.4f} | "
          f"gap={gap:.4f}")
    if gap > OVERFIT_GAP_THRESHOLD:
        print("⚠️ 训练集与测试集分数差距较大，可能过拟合")

    # ★ 修复 G：WF 用 train_df，绝不污染 test
    wf_results = (
        walk_forward_validation(train_df, best_param, n_splits=4)
        if enable_wf else []
    )
    if wf_results:
        for r in wf_results:
            print(f"  段{r['segment']} {r['start']}~{r['end']}: "
                  f"score={r['score']:.3f} trades={r['total_closed']}")

    # 绘图
    if mode == "grid":
        plot_grid_heatmap(); plot_stability_analysis()
    plot_train_test_comparison()
    if wf_results:
        plot_walk_forward(wf_results)

    return {
        "best_param": best_param,
        "train_score": best_score_train,
        "test_score": score_test,
        "wf_results": wf_results,
    }


def _run_with_fresh_cache(param, df):
    """在测试前清缓存，避免之前 train 阶段的回测命中陈旧结果。"""
    clear_caches()
    from .backtest import run_backtest
    return run_backtest(param, df)


def real_dry() -> dict:
    """Real 模式 dry-run：不读 TDX（用 mock），验证 select_at_open 链路。"""
    from .real import select_at_open, load_best_param
    mock_df = load_data(mode="mock", n_stocks=20, n_days=120)
    mock_df["datetime"] = pd.to_datetime(mock_df["datetime"])
    today = mock_df["datetime"].max().strftime("%Y-%m-%d")
    # 先快速训练得到 best_param（用 5 组网格）
    os.environ.setdefault("XGDA_FAST_TRAIN", "1")
    res = train_pipeline(mode="grid", data_mode="mock", enable_wf=False)
    # 用训练结果跑 select_at_open
    best_param = res["best_param"]
    return select_at_open(
        today=today, today_df=mock_df,
        best_param={"z_min": int(best_param["z_min"]),
                    "z_max": int(best_param["z_max"]),
                    "score": res["train_score"]},
        output_dir="output", interactive_guard=False,
    )


def real_once() -> dict:
    """立即跑 9:25 选股（覆盖时序检查）。"""
    from .real import select_at_open, load_best_param, load_tdx7
    print("[real-once] 读取 tdx7 真实数据…")
    all_data = load_tdx7()
    best_param = load_best_param()
    today = pd.Timestamp.now().strftime("%Y-%m-%d")
    return select_at_open(
        today=today, today_df=all_data, best_param=best_param,
        output_dir="output", interactive_guard=False,
    )


def main():
    parser = argparse.ArgumentParser(description="XGDA v3.1 入口")
    parser.add_argument("--mode", default=RUN_MODE,
                        choices=["grid", "ga"], help="寻参模式")
    parser.add_argument("--data", default="mock",
                        choices=["mock", "tdx7"], help="数据源")
    parser.add_argument("--enable-wf", action="store_true",
                        help="启用 walk-forward（慢）")
    parser.add_argument("--test-split", default=TEST_SPLIT_DATE,
                        help="样本外切分点")
    parser.add_argument("--real-dry", action="store_true",
                        help="Real 模式 dry-run（mock 数据）")
    parser.add_argument("--real-once", action="store_true",
                        help="Real 模式立即跑选股（跳过时序检查）")
    args = parser.parse_args()

    if args.real_dry:
        print("==== Real Dry-Run ====")
        return real_dry()
    if args.real_once:
        print("==== Real Once ====")
        return real_once()
    return train_pipeline(
        mode=args.mode, data_mode=args.data,
        enable_wf=args.enable_wf, test_split=args.test_split,
    )


if __name__ == "__main__":
    main()

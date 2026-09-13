"""参数自进化 (网格 + GA + 样本外 + Walk-Forward)

修复 G 项：walk_forward_validation 接受 data 参数（train_df 或 full_df），
由 __main__ 决定传什么；v3.1 默认用 train_df，绝不污染泛化测试集。
"""
import os
import time
import random
import numpy as np
import pandas as pd

from .config import (
    PARAM_SPACE, POP_SIZE, GENERATIONS, MUTATION_RATE, CROSSOVER_RATE,
    SCORE_VALID_FLOOR,
    MIN_TRADE_COUNT, MIN_TRADE_COUNT_TEST,
    HOLD_DAYS, STOP_LOSS_RATE, MAX_POS_COUNT,
    COMMISSION, SLIPPAGE, STRATEGY_SEED, INIT_CASH,
    RISK_FREE_ANNUAL, TRADING_DAYS,
    RESULT_CSV_TRAIN, RESULT_CSV_WF,
)
from .io_csv import write_result_csv
from .scoring import calc_score
from .backtest import run_backtest


# =============================================================================
# 工具函数
# =============================================================================
def _param_grid_lists() -> dict:
    """从 PARAM_SPACE 派生网格列表（v3.0 修复 14）。"""
    out = {}
    for (name, lo, hi, step, is_int, _) in PARAM_SPACE:
        rng = list(range(lo, hi + 1, step))
        out[name] = rng
    return out


def _param_names() -> list:
    return [p[0] for p in PARAM_SPACE]


# ---- GA 个体工具 ----
def normalize_ind(ind):
    """保证 z_min < z_max（顺序反向则交换）。"""
    if len(ind) >= 2 and ind[0] > ind[1]:
        ind[0], ind[1] = ind[1], ind[0]
    return ind


def random_individual() -> list:
    ind = []
    for (_, lo, hi, _, is_int, _) in PARAM_SPACE:
        v = random.uniform(lo, hi)
        if is_int:
            v = float(round(v))
        ind.append(v)
    return normalize_ind(ind)


def decode(ind) -> dict:
    param_dict = {}
    for i, (name, lo, hi, _, is_int, _) in enumerate(PARAM_SPACE):
        v = ind[i]
        v = float(np.clip(v, lo, hi))
        if is_int:
            v = float(round(v))
        param_dict[name] = v
    if "z_min" in param_dict and "z_max" in param_dict \
            and param_dict["z_min"] >= param_dict["z_max"]:
        param_dict["z_min"], param_dict["z_max"] = (
            param_dict["z_max"], param_dict["z_min"]
        )
    return param_dict


def _df_fingerprint(all_df) -> tuple:
    """带缓存的数据集指纹（v3.0 修复 6）。"""
    from .config import _FP_CACHE
    if len(all_df) == 0:
        return (0, "", "", 0)
    key = id(all_df)
    if key in _FP_CACHE:
        return _FP_CACHE[key]
    dts = all_df["datetime"]
    fp = (
        len(all_df),
        str(dts.min()),
        str(dts.max()),
        int(all_df["code"].nunique()),
    )
    _FP_CACHE[key] = fp
    return fp


def fitness(ind, all_df) -> float:
    """GA 适应度：参数 → 回测 → 评分（含缓存命中）。"""
    from .config import _FIT_CACHE
    ind = normalize_ind(ind[:])
    params = decode(ind)
    fp = _df_fingerprint(all_df)
    key = (
        fp,
        tuple(round(v, 6) for v in ind),
        HOLD_DAYS, STOP_LOSS_RATE, MAX_POS_COUNT, MIN_TRADE_COUNT,
        COMMISSION, SLIPPAGE, STRATEGY_SEED, INIT_CASH,
        RISK_FREE_ANNUAL, TRADING_DAYS,
    )
    if key in _FIT_CACHE:
        return _FIT_CACHE[key]
    res = run_backtest(params, all_df)
    score = calc_score(res, min_trades=MIN_TRADE_COUNT, use_gradient=True)
    _FIT_CACHE[key] = float(score)
    return float(score)


def select(pop, scores, k=3):
    k = min(k, len(pop))
    sample_idx = random.sample(range(len(pop)), k)
    best_idx = max(sample_idx, key=lambda i: scores[i])
    return pop[best_idx][:]


def crossover(a, b):
    if random.random() < CROSSOVER_RATE and len(a) > 1:
        cut = random.randint(1, len(a) - 1)
        return a[:cut] + b[cut:], b[:cut] + a[cut:]
    return a[:], b[:]


def mutate(ind):
    for i, (_, lo, hi, step, is_int, _) in enumerate(PARAM_SPACE):
        if random.random() < MUTATION_RATE:
            v = ind[i] + random.uniform(-step, step)
            v = float(np.clip(v, lo, hi))
            if is_int:
                v = float(round(v))
            ind[i] = v
    return normalize_ind(ind)


# =============================================================================
# 1. 网格搜索（v3.0 修复 9/14：边界派生 + 进度打印）
# =============================================================================
def grid_search(all_df: pd.DataFrame, result_csv: str = RESULT_CSV_TRAIN):
    """网格搜索最优参数。"""
    print("======== 网格搜索开始 ========")
    grid = _param_grid_lists()
    pnames = _param_names()
    # 暂只支持 z_min/z_max 网格
    if "z_min" in grid and "z_max" in grid:
        z_min_list = grid["z_min"]
        z_max_list = grid["z_max"]
        tasks = [(a, b) for a in z_min_list for b in z_max_list if a < b]
    else:
        raise ValueError("当前 PARAM_SPACE 仅实现 z_min/z_max 网格")

    best_score = -1e9
    best_param = None
    best_res = None
    t0 = time.time()

    for i, (z_min, z_max) in enumerate(tasks, 1):
        param = {"z_min": z_min, "z_max": z_max}
        res = run_backtest(param, all_df)
        score = calc_score(res, min_trades=MIN_TRADE_COUNT, use_gradient=True)
        write_result_csv(result_csv, param, score, res,
                         mode="grid", tag="train")
        if i % 20 == 0 or i == len(tasks):
            print(
                f"[{i:>3}/{len(tasks)}] z=[{z_min},{z_max}] "
                f"score={score:>7.3f} trades={res['total_closed']:>4} "
                f"ret={res['final_value']/INIT_CASH-1:>7.2%} "
                f"dd={res['max_drawdown']:>6.2%} "
                f"win={res['win_rate']:>6.2%}"
            )
        if score > best_score:
            best_score = score
            best_param = param
            best_res = res

    elapsed = time.time() - t0
    print(f"\n网格耗时: {elapsed:.1f}s（{len(tasks)} 组，"
          f"平均 {elapsed/len(tasks):.2f}s/组）")
    print("======== 网格搜索最优 ========")
    print(f"参数: {best_param}")
    print(f"得分: {best_score:.4f}")
    if best_res:
        print(f"交易笔数: {best_res['total_closed']}")
        print(f"胜率: {best_res['win_rate']:.2%}")
        print(f"最终市值: {best_res['final_value']:.2f}")
        print(f"最大回撤: {best_res['max_drawdown']:.2%}")
    return best_param, best_score


# =============================================================================
# 2. 遗传算法（v3.0 修复 4/9：写 train CSV + 停滞阈值对齐）
# =============================================================================
def genetic_search(all_df: pd.DataFrame,
                   result_csv: str = RESULT_CSV_TRAIN):
    """遗传算法最优参数（也会写 train CSV，便于对比图 GA 模式可用）。"""
    print("======== 遗传算法开始 ========")
    pop = [random_individual() for _ in range(POP_SIZE)]
    best_ever_score = -1e9
    best_ever_ind = None

    for gen in range(GENERATIONS):
        scores = [fitness(ind, all_df) for ind in pop]
        best_idx = int(np.argmax(scores))
        if scores[best_idx] > best_ever_score:
            best_ever_score = scores[best_idx]
            best_ever_ind = pop[best_idx][:]
        best_params = decode(pop[best_idx])
        print(
            f"【第{gen+1:02d}代】最优={scores[best_idx]:>7.3f} "
            f"| 历史最优={best_ever_score:>7.3f} "
            f"| 参数={best_params}"
        )

        if scores[best_idx] < SCORE_VALID_FLOOR:
            keep = [pop[best_idx][:]]
            for _ in range(POP_SIZE // 2):
                keep.append(random_individual())
            while len(keep) < POP_SIZE:
                keep.append(select(pop, scores))
            pop = keep
            continue

        new_pop = [pop[best_idx][:]]
        while len(new_pop) < POP_SIZE:
            p1 = select(pop, scores)
            p2 = select(pop, scores)
            c1, c2 = crossover(p1, p2)
            c1 = mutate(c1)
            c2 = mutate(c2)
            new_pop.append(c1)
            if len(new_pop) < POP_SIZE:
                new_pop.append(c2)
        pop = new_pop

    final_scores = [fitness(i, all_df) for i in pop]
    local_best_idx = int(np.argmax(final_scores))
    if final_scores[local_best_idx] > best_ever_score:
        best_ever_ind = pop[local_best_idx][:]
        best_ever_score = final_scores[local_best_idx]

    final_param = decode(best_ever_ind)
    final_res = run_backtest(final_param, all_df)
    write_result_csv(result_csv, final_param, best_ever_score,
                     final_res, mode="ga", tag="train")

    print("\n======== GA 最优 ========")
    print(f"参数: {final_param}")
    print(f"得分: {best_ever_score:.4f}")
    return final_param, best_ever_score


# =============================================================================
# 3. Walk-Forward（v3.1 修复 G：data 由调用方传入，避免污染泛化测试）
# =============================================================================
def walk_forward_validation(data: pd.DataFrame, param: dict,
                            n_splits: int = 4) -> list:
    """Walk-Forward 滚动验证。

    Args:
        data: 数据源。强烈建议传入 train_df 而非全量数据，
              避免泛化测试集被 WF 触及（v3.1 修复 G）。
        param: best_param（来自 grid/GA 寻参结果）
        n_splits: 滚动段数

    Returns:
        list of dict: 每段 score / sharpe / win_rate / max_drawdown /
              calmar / total_closed / final_value / segment / start / end
    """
    if len(data) == 0 or n_splits < 2:
        return []
    data = data.sort_values("datetime").copy()
    t_min, t_max = data["datetime"].min(), data["datetime"].max()
    edges = pd.date_range(t_min, t_max, periods=n_splits + 1)
    results = []
    for i in range(n_splits):
        seg = data[
            (data["datetime"] >= edges[i])
            & (data["datetime"] < edges[i + 1])
        ]
        if len(seg) == 0:
            continue
        res = run_backtest(param, seg)
        score = calc_score(res, min_trades=MIN_TRADE_COUNT_TEST,
                           use_gradient=True)
        results.append({
            "segment": i + 1,
            "start": str(edges[i].date()),
            "end": str(edges[i + 1].date()),
            "score": score,
            "sharpe": res["sharpe"],
            "win_rate": res["win_rate"],
            "max_drawdown": res["max_drawdown"],
            "calmar": res["calmar"],
            "total_closed": res["total_closed"],
            "final_value": res["final_value"],
        })
        write_result_csv(
            RESULT_CSV_WF,
            {"z_min": param["z_min"], "z_max": param["z_max"]},
            score, res, mode="walkforward", tag=f"seg{i+1}",
        )
    return results

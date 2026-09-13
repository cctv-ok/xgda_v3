"""绘图：热力图 / 稳定性分析 / Train-Test 对比 / Walk-Forward

依赖：matplotlib, seaborn（仅在调用 plot_* 时按需 import）
中文字体缓存：lru_cache（v3.0 修复 13）
"""
import os
import functools
import numpy as np
import pandas as pd

from .config import RESULT_CSV_TRAIN, RESULT_CSV_TEST, MIN_TRADE_COUNT


@functools.lru_cache(maxsize=1)
def _setup_chinese_font():
    """中文字体探测（lru_cache 避免重复扫描 ttflist）。"""
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
    candidates = [
        "Microsoft YaHei", "SimHei", "PingFang SC",
        "Hiragino Sans GB", "Noto Sans CJK SC", "WenQuanYi Micro Hei",
    ]
    available = {f.name for f in fm.fontManager.ttflist}
    for name in candidates:
        if name in available:
            plt.rcParams["font.sans-serif"] = [name]
            plt.rcParams["axes.unicode_minus"] = False
            return name
    plt.rcParams["axes.unicode_minus"] = False
    return None


def _load_grid_results(csv_path: str) -> pd.DataFrame:
    if not os.path.exists(csv_path):
        return pd.DataFrame()
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    return df[df["run_mode"] == "grid"].copy()


def plot_grid_heatmap(csv_path=RESULT_CSV_TRAIN,
                      out_png="xgda_heatmap.png",
                      metric="score"):
    """单指标热力图 + 双面板 (score+trades)。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    import seaborn as sns

    df = _load_grid_results(csv_path)
    if len(df) == 0:
        print(f"[heatmap] {csv_path} 无 grid 模式结果，跳过")
        return

    _setup_chinese_font()
    pivot = df.pivot_table(
        index="z_min", columns="z_max", values=metric, aggfunc="mean"
    ).sort_index(ascending=True).sort_index(axis=1, ascending=True)
    pivot_trades = df.pivot_table(
        index="z_min", columns="z_max", values="total_closed", aggfunc="mean"
    ).sort_index(ascending=True).sort_index(axis=1, ascending=True)
    best_idx = df[metric].idxmax()
    best_row = df.loc[best_idx]
    best_zmin, best_zmax = best_row["z_min"], best_row["z_max"]
    best_val = best_row[metric]

    # ---- 单指标热力图 ----
    fig, ax = plt.subplots(figsize=(12, 9))
    sns.heatmap(pivot, ax=ax, cmap="RdYlGn", center=0,
                annot=True, fmt=".3f", annot_kws={"size": 8},
                linewidths=0.5, linecolor="white",
                cbar_kws={"label": metric})
    if best_zmin in pivot.index and best_zmax in pivot.columns:
        x = list(pivot.columns).index(best_zmax)
        y = list(pivot.index).index(best_zmin)
        ax.add_patch(Rectangle((x, y), 1, 1, fill=False,
                               edgecolor="black", lw=2.5))
        ax.text(x + 0.5, y + 1.15, f"★ best={best_val:.3f}",
                ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax.set_title(f"XGDA Grid ({metric})\nbest: z_min={best_zmin}, "
                 f"z_max={best_zmax}, {metric}={best_val:.4f}", fontsize=13)
    ax.set_xlabel("z_max (亿)"); ax.set_ylabel("z_min (亿)")
    plt.tight_layout()
    plt.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[heatmap] 已保存: {out_png}")

    # ---- 双面板 ----
    dual_png = out_png.replace(".png", "_dual.png")
    fig, axes = plt.subplots(1, 2, figsize=(20, 9))
    sns.heatmap(pivot, ax=axes[0], cmap="RdYlGn", center=0,
                annot=True, fmt=".3f", annot_kws={"size": 7},
                linewidths=0.5, linecolor="white",
                cbar_kws={"label": "score"})
    axes[0].set_title(f"Score ({metric})", fontsize=12)
    axes[0].set_xlabel("z_max (亿)"); axes[0].set_ylabel("z_min (亿)")
    if best_zmin in pivot.index and best_zmax in pivot.columns:
        x = list(pivot.columns).index(best_zmax)
        y = list(pivot.index).index(best_zmin)
        axes[0].add_patch(Rectangle((x, y), 1, 1, fill=False,
                                    edgecolor="black", lw=2.5))
    sns.heatmap(pivot_trades, ax=axes[1], cmap="Blues",
                annot=True, fmt=".0f", annot_kws={"size": 7},
                linewidths=0.5, linecolor="white",
                cbar_kws={"label": "total_closed"})
    axes[1].set_title("Trade Count", fontsize=12)
    axes[1].set_xlabel("z_max (亿)"); axes[1].set_ylabel("z_min (亿)")
    for yi in range(pivot_trades.shape[0]):
        for xi in range(pivot_trades.shape[1]):
            v = pivot_trades.iloc[yi, xi]
            if pd.notna(v) and v < MIN_TRADE_COUNT:
                axes[1].add_patch(Rectangle((xi, yi), 1, 1, fill=False,
                                            edgecolor="red", lw=1.2,
                                            linestyle="--"))
    fig.suptitle(
        f"XGDA Grid: Score + Trade\n"
        f"(红虚线 = trades < {MIN_TRADE_COUNT} 无效区)",
        fontsize=13,
    )
    plt.tight_layout()
    plt.savefig(dual_png, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[heatmap] 已保存: {dual_png}")


def plot_stability_analysis(csv_path=RESULT_CSV_TRAIN,
                            out_png="xgda_stability.png"):
    """最优参数 3x3 邻域稳定性分析。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns

    df = _load_grid_results(csv_path)
    if len(df) == 0:
        print(f"[stability] {csv_path} 无 grid 结果，跳过")
        return

    _setup_chinese_font()
    pivot = df.pivot_table(
        index="z_min", columns="z_max", values="score", aggfunc="mean"
    ).sort_index(ascending=True).sort_index(axis=1, ascending=True)
    best_pos = np.unravel_index(np.nanargmax(pivot.values), pivot.shape)
    by, bx = best_pos
    best_zmin = pivot.index[by]
    best_zmax = pivot.columns[bx]
    best_score = pivot.iloc[by, bx]
    y0, y1 = max(by - 1, 0), min(by + 2, pivot.shape[0])
    x0, x1 = max(bx - 1, 0), min(bx + 2, pivot.shape[1])
    local = pivot.iloc[y0:y1, x0:x1]
    local_mean = float(np.nanmean(local.values))
    local_std = float(np.nanstd(local.values))
    local_min = float(np.nanmin(local.values))

    fig, ax = plt.subplots(figsize=(7, 6))
    sns.heatmap(local, ax=ax, cmap="RdYlGn", center=0,
                annot=True, fmt=".3f", annot_kws={"size": 11},
                linewidths=0.8, linecolor="white",
                cbar_kws={"label": "score"})
    ax.set_title(
        f"Stability 3x3 of best (z_min={best_zmin}, z_max={best_zmax})\n"
        f"score={best_score:.4f} | mean={local_mean:.4f} "
        f"std={local_std:.4f} min={local_min:.4f}",
        fontsize=11,
    )
    ax.set_xlabel("z_max (亿)"); ax.set_ylabel("z_min (亿)")
    plt.tight_layout()
    plt.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[stability] 已保存: {out_png}")

    if local_std > 0.5 * abs(best_score) and best_score > 0:
        print("[stability] ⚠️ 邻域波动大，可能是孤岛峰值（过拟合信号）")
    else:
        print("[stability] ✅ 邻域平稳，最优点相对稳健")


def plot_train_test_comparison(train_csv=RESULT_CSV_TRAIN,
                               test_csv=RESULT_CSV_TEST,
                               out_png="xgda_train_test_compare.png"):
    """Train vs Test 对比柱状图 + 汇总表。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if not os.path.exists(train_csv) or not os.path.exists(test_csv):
        print("[compare] 缺少 train 或 test CSV，跳过")
        return
    df_train = pd.read_csv(train_csv, encoding="utf-8-sig")
    df_test = pd.read_csv(test_csv, encoding="utf-8-sig")
    if len(df_train) == 0 or len(df_test) == 0:
        return

    df_train_grid = df_train[df_train["run_mode"] == "grid"].copy()
    if len(df_train_grid) == 0:
        df_train_grid = df_train.copy()
    best_idx = df_train_grid["score"].idxmax()
    best_row = df_train_grid.loc[best_idx]
    best_zmin, best_zmax = best_row["z_min"], best_row["z_max"]
    train_row = df_train_grid[
        (df_train_grid["z_min"] == best_zmin)
        & (df_train_grid["z_max"] == best_zmax)
    ].iloc[0]
    test_row = df_test.iloc[0]

    if (test_row["z_min"] != best_zmin) or (test_row["z_max"] != best_zmax):
        print("[compare] ⚠️ test CSV 参数与 train 最优不一致")

    _setup_chinese_font()
    metrics = [
        ("score", "Score", False),
        ("sharpe", "Sharpe", False),
        ("win_rate", "Win Rate", True),
        ("max_drawdown", "Max DD", True),
        ("calmar", "Calmar", False),
    ]
    train_vals = [float(train_row[m[0]]) for m in metrics]
    test_vals = [float(test_row[m[0]]) for m in metrics]
    x = np.arange(len(metrics))
    width = 0.35
    fig, axes = plt.subplots(1, 2, figsize=(18, 7),
                             gridspec_kw={"width_ratios": [2.2, 1]})

    ax = axes[0]
    bars1 = ax.bar(x - width / 2, train_vals, width, label="Train",
                   color="#2E86AB", alpha=0.85,
                   edgecolor="black", linewidth=0.6)
    bars2 = ax.bar(x + width / 2, test_vals, width, label="Test",
                   color="#E63946", alpha=0.85,
                   edgecolor="black", linewidth=0.6)
    for bar, val, (_, _, is_pct) in zip(bars1, train_vals, metrics):
        label = f"{val:.2%}" if is_pct else f"{val:.3f}"
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                label, ha="center", va="bottom", fontsize=9,
                color="#0B3C5D", fontweight="bold")
    for bar, val, (_, _, is_pct) in zip(bars2, test_vals, metrics):
        label = f"{val:.2%}" if is_pct else f"{val:.3f}"
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                label, ha="center", va="bottom", fontsize=9,
                color="#7A1F1F", fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels([m[1] for m in metrics], fontsize=11)
    ax.axhline(0, color="gray", linewidth=0.8)
    ax.set_title(
        f"Train vs Test — Best (z_min={best_zmin}, z_max={best_zmax})",
        fontsize=13,
    )
    ax.set_ylabel("Value")
    ax.legend(loc="upper right", fontsize=10)
    ax.grid(axis="y", alpha=0.3, linestyle="--")

    ax_table = axes[1]
    ax_table.axis("off")
    table_data = []
    for (key, name_en, is_pct), tv, tev in zip(metrics, train_vals, test_vals):
        tr = f"{tv:.2%}" if is_pct else f"{tv:.3f}"
        te = f"{tev:.2%}" if is_pct else f"{tev:.3f}"
        table_data.append([name_en, tr, te])
    table = ax_table.table(
        cellText=table_data,
        colLabels=["指标", "Train", "Test"],
        loc="center", cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1, 2)
    ax_table.set_title("指标汇总表", fontsize=13)

    plt.tight_layout()
    plt.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[train_test_compare] 已保存: {out_png}")


def plot_walk_forward(wf_results: list,
                      out_png: str = "xgda_walkforward.png"):
    """Walk-Forward 各段得分 + 交易笔数（双轴）。"""
    if not wf_results:
        print("[walkforward] 无结果，跳过")
        return
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _setup_chinese_font()
    segs = [r["segment"] for r in wf_results]
    scores = [r["score"] for r in wf_results]
    trades = [r["total_closed"] for r in wf_results]
    labels = [f"{r['start']}\n~{r['end']}" for r in wf_results]

    fig, ax1 = plt.subplots(figsize=(12, 6))
    color1 = "#2E86AB"
    ax1.set_xlabel("时间段")
    ax1.set_ylabel("Score", color=color1)
    bars = ax1.bar(segs, scores, color=color1, alpha=0.7,
                   edgecolor="black", linewidth=0.6)
    ax1.tick_params(axis="y", labelcolor=color1)
    ax1.set_xticks(segs); ax1.set_xticklabels(labels, fontsize=9)
    ax1.axhline(0, color="gray", linewidth=0.8)
    for bar, s in zip(bars, scores):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                 f"{s:.3f}", ha="center", va="bottom", fontsize=9)

    ax2 = ax1.twinx()
    color2 = "#E63946"
    ax2.set_ylabel("Trade Count", color=color2)
    ax2.plot(segs, trades, color=color2, marker="o",
             linewidth=2, label="Trades")
    ax2.tick_params(axis="y", labelcolor=color2)
    for xi, t in zip(segs, trades):
        ax2.text(xi, t, f"{t}", ha="center", va="bottom",
                 fontsize=9, color=color2)

    plt.title("Walk-Forward Validation", fontsize=13)
    fig.tight_layout()
    plt.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[walkforward] 已保存: {out_png}")

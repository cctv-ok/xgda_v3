"""Real 模式：盘中 9:25 集合竞价结束 → 立即选股

时序：
    09:25:00  集合竞价结束，得到各股开盘价 + 撮合量
    09:25:01  触发本模块 select_at_open()
              ↓
    1. 加载昨日 best_param（来自 result_csv 或缓存）
    2. xgda_signal → 候选集
    3. ★ L2 实时盘口二次校验（可选，--l2-verify）
       - 集合竞价匹配量 / 买卖盘比 / 流动性 → 综合得分
       - 与 XGDA 信号分加权 → 重新排序
    4. 按 max_pos 截断，输出选股清单（json + txt）

防坑：
    * 9:25 之前调用直接返回 + 警告（避免盘中噪声干扰）
    * TDX TCP 失败 → 走 fallback：仅基于 XGDA 信号分（l2_score 返回 0）
    * L2 不可用时降级为 unknown=True 的 L2Quote，不阻塞流程
    * 输出 atomic write（tmp + rename）
"""
import json
import os
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict

import pandas as pd

from .config import (
    MAX_POS_COUNT, TEST_SPLIT_DATE,
    RESULT_CSV_TRAIN, TDX_SOCKET_HOST, TDX_SOCKET_PORT,
    HOLD_DAYS, STOP_LOSS_RATE,
)
from .signal import xgda_signal
from .data_source import load_tdx7
from xgda.data_source.tdx_socket import (
    L2QuoteFetcher, NoopL2Fetcher, make_l2_fetcher,
)
from xgda.data_source.l2_verify import (
    verify_with_l2, filter_top_n,
)


DEFAULT_OUTPUT_DIR = "output"

# 是否启用 L2 验证（可通过 select_at_open(..., l2_verify=True) 覆盖）
L2_VERIFY_DEFAULT = False

# XGDA 与 L2 加权（XGDA=0.6, L2=0.4），可通过 select_at_open(..., l2_weights=(...))
L2_WEIGHTS_DEFAULT = (0.6, 0.4)


def load_best_param(csv_path: str = RESULT_CSV_TRAIN) -> Optional[Dict]:
    """从 train CSV 读 best_param（最高分对应行）。

    Returns:
        dict 或 None（CSV 不存在 / 无 grid 结果）
    """
    if not os.path.exists(csv_path):
        return None
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    if len(df) == 0:
        return None
    df_grid = df[df["run_mode"] == "grid"]
    if len(df_grid) > 0:
        df = df_grid
    row = df.loc[df["score"].idxmax()]
    return {
        "z_min": int(row["z_min"]) if pd.notna(row["z_min"]) else None,
        "z_max": int(row["z_max"]) if pd.notna(row["z_max"]) else None,
        "score": float(row["score"]),
    }


def _normalize_xg_score(score: float, score_lo: float = -1.0,
                        score_hi: float = 1.0) -> float:
    """把 XGDA 训练的 score 映射到 0-1 范围。

    训练 score 范围大致 [-1, 1]（受 SCORE_INVALID_FLOOR / CALMAR 等影响），
    这里用线性映射便于和 L2 分数加权。
    """
    if score >= score_hi:
        return 1.0
    if score <= score_lo:
        return 0.0
    return (score - score_lo) / (score_hi - score_lo)


def select_at_open(today: str = None,
                   today_df: pd.DataFrame = None,
                   best_param: Dict = None,
                   tdx_host: str = TDX_SOCKET_HOST,
                   tdx_port: int = TDX_SOCKET_PORT,
                   output_dir: str = DEFAULT_OUTPUT_DIR,
                   interactive_guard: bool = True,
                   l2_verify: bool = L2_VERIFY_DEFAULT,
                   l2_fetcher: Optional[L2QuoteFetcher] = None,
                   l2_weights: tuple = L2_WEIGHTS_DEFAULT,
                   ) -> Dict:
    """9:25 盘中选股主入口。

    Args:
        today: YYYY-MM-DD；None 时用今日
        today_df: 当日盘后完整 dataframe（含 T-1 数据）；
                  None 时自动 load_tdx7()
        best_param: 来自 load_best_param(); None 时自动从 CSV 读
        tdx_host, tdx_port: 通达信 TCP（暂未启用实时，仅记录）
        output_dir: 输出目录
        interactive_guard: True 时检查 9:25 时序，未到时间警告并退出
        l2_verify: True → 拉 L2 实时盘口二次校验
        l2_fetcher: L2 抓取器；None → NoopL2Fetcher（不连真实 L2）
        l2_weights: (XGDA权重, L2权重)

    Returns:
        dict: {
            'selected': [{'code', 'final_score', 'xg_score', 'l2_score',
                          'l2_unknown', 'close', 'circ_value_z'}, ...],
            'param': best_param,
            'timestamp': ISO,
            'output_json': 'path',
            'output_txt': 'path',
            'l2_active': bool,
        }
    """
    if interactive_guard:
        now = datetime.now()
        if (now.hour, now.minute) < (9, 25):
            print(f"[select_at_open] ⚠️ 当前 {now.strftime('%H:%M:%S')} < 09:25，"
                  f"未到选股时点。")
            return {"selected": [], "param": None, "skipped": True}

    today = today or datetime.now().strftime("%Y-%m-%d")
    if best_param is None:
        best_param = load_best_param()
    if best_param is None or best_param.get("z_min") is None:
        print("[select_at_open] ⚠️ 无 best_param，请先跑 grid_search/GA 训练")
        return {"selected": [], "param": None, "skipped": "no_param"}

    if today_df is None:
        all_data = load_tdx7()
        all_data["datetime"] = pd.to_datetime(all_data["datetime"])
        cutoff = pd.Timestamp(today)
        today_df = all_data[all_data["datetime"] <= cutoff].copy()

    # ---------- Step 1: XGDA 信号初筛 ----------
    xg = xgda_signal(today_df, best_param)
    today_df = today_df.copy()
    today_df["xg"] = xg.values
    today_only = today_df[
        today_df["datetime"].astype(str).str.startswith(today)
    ].copy()
    candidates = today_only[today_only["xg"] == 1].copy()

    if len(candidates) == 0:
        print(f"[select_at_open] {today} 今日无候选（xg 全 0）")
        result = {
            "selected": [],
            "param": best_param,
            "date": today,
            "timestamp": datetime.now().isoformat(),
            "skipped": "no_candidate",
            "l2_active": l2_verify,
        }
        _write_outputs(result, output_dir)
        return result

    # XGDA signal 在 calc_score 里是聚合打分，在 grid 训练时已存在每行的 score 字段
    # 但 candidates 是按 (code, today) 取的，这里重新算一遍"个股分数"近似
    # 实际生产可用 XGDA score * circ_value_z 衰减，但避免复杂度，先用归一化 score
    raw_xg_score = float(best_param.get("score", 0.5))
    base_score = _normalize_xg_score(raw_xg_score)
    candidates.sort_values("circ_value_z", ascending=True, inplace=True)

    cand_codes = candidates["code"].astype(str).str.zfill(6).tolist()
    xg_score_map = {c: base_score for c in cand_codes}

    selected_records: List[Dict] = []
    l2_active = False

    if l2_verify:
        # ---------- Step 2: L2 实时盘口二次校验 ----------
        l2_active = True
        fetcher = l2_fetcher or NoopL2Fetcher()
        # cctv 真实部署时通过 l2_fetcher=TcpL2Fetcher(host=tdx_host, port=tdx_port) 注入
        try:
            fetcher.connect()
        except Exception as e:
            print(f"[select_at_open] ⚠️ L2 fetcher.connect 失败: {e}; 降级为 NoopL2Fetcher")
            fetcher = NoopL2Fetcher()
            fetcher.connect()

        verified = verify_with_l2(
            candidate_codes=cand_codes,
            xg_scores=xg_score_map,
            fetcher=fetcher,
            weights=l2_weights,
        )
        # 取前 max_pos
        top = filter_top_n(verified, top_n=MAX_POS_COUNT)

        for vc in top:
            c_row = candidates[candidates["code"] == vc.code]
            if len(c_row) == 0:
                continue
            row = c_row.iloc[0]
            selected_records.append({
                "code": vc.code,
                "close": float(row.get("close", 0.0)),
                "circ_value_z": float(row.get("circ_value_z", 0.0)),
                "xg_score": round(vc.xg_score, 4),
                "l2_score": round(vc.l2_score, 4),
                "l2_unknown": vc.quote.unknown,
                "final_score": round(vc.final_score, 4),
                "l2_notes": "; ".join(vc.notes),
                "match_volume": vc.quote.call_auction_match_volume,
                "ba_ratio": (round(vc.quote.bid_ask_ratio(), 3)
                             if vc.quote.bid_ask_ratio() is not None else None),
            })

        # 反向标记：L2 拒掉的候选（final_score 极低）
        if len(top) < len(cand_codes):
            kept = {r["code"] for r in selected_records}
            rejected_codes = [c for c in cand_codes if c not in kept]
            if rejected_codes:
                print(f"[select_at_open] L2 拒掉 {len(rejected_codes)} 只候选: "
                      f"{rejected_codes[:5]}...")

        try:
            fetcher.disconnect()
        except Exception:
            pass
    else:
        # 旧路径：只截取 max_pos，按 circ_value_z 升序
        selected = candidates.head(MAX_POS_COUNT)
        for _, row in selected.iterrows():
            selected_records.append({
                "code": str(row["code"]).zfill(6),
                "close": float(row.get("close", 0.0)),
                "circ_value_z": float(row.get("circ_value_z", 0.0)),
                "xg_score": round(base_score, 4),
                "l2_score": 0.0,
                "l2_unknown": True,
                "final_score": round(base_score, 4),
                "l2_notes": "L2 未启用",
                "match_volume": None,
                "ba_ratio": None,
            })

    result = {
        "selected": selected_records,
        "param": best_param,
        "date": today,
        "timestamp": datetime.now().isoformat(),
        "l2_active": l2_active,
        "l2_weights": list(l2_weights),
        "candidates_total": len(cand_codes),
        "selected_total": len(selected_records),
    }

    _write_outputs(result, output_dir)
    return result


def _write_outputs(result: Dict, output_dir: str) -> None:
    """写选股结果到 JSON + 可读 TXT（atomic write）。"""
    os.makedirs(output_dir, exist_ok=True)
    today = result.get("date") or datetime.now().strftime("%Y-%m-%d")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    base = os.path.join(output_dir, f"select_{today}_{ts}")
    json_path = base + ".json"
    txt_path = base + ".txt"
    tmp_json = json_path + ".tmp"
    tmp_txt = txt_path + ".tmp"

    # JSON
    with open(tmp_json, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp_json, json_path)

    # TXT（人类可读 + TDX 粘贴）
    with open(tmp_txt, "w", encoding="utf-8") as f:
        f.write(f"# XGDA Real 9:25 选股 {today}\n")
        f.write(f"# best_param = {result.get('param')}\n")
        f.write(f"# 生成时间: {result.get('timestamp')}\n")
        f.write(f"# 持仓上限: {MAX_POS_COUNT}\n")
        f.write(f"# L2 验证: {'启用' if result.get('l2_active') else '禁用'}\n")
        if result.get("l2_active"):
            f.write(f"# L2 权重: {result.get('l2_weights')}\n")
        f.write(f"# 候选数: {result.get('candidates_total', '?')} | "
                f"入选数: {result.get('selected_total', '?')}\n\n")

        sel = result.get("selected", [])
        if not sel:
            f.write("(无入选)\n")
        for i, r in enumerate(sel, 1):
            l2_mark = "✓" if not r.get("l2_unknown") else "○"
            line = (f"{i:>2}. {r['code']} | close={r['close']:.2f} | "
                    f"circ_z={r['circ_value_z']:.3f} | "
                    f"xg={r['xg_score']:.3f} | "
                    f"l2={l2_mark}{r['l2_score']:.3f} | "
                    f"final={r['final_score']:.3f}")
            if r.get("match_volume"):
                line += f" | match={r['match_volume']}"
            if r.get("ba_ratio") is not None:
                line += f" | b/a={r['ba_ratio']:.2f}"
            f.write(line + "\n")

    os.replace(tmp_txt, txt_path)

    print(f"[select_at_open] ✓ {len(sel)} 只票 → {txt_path}")
    result["output_json"] = json_path
    result["output_txt"] = txt_path


class DailyRunner:
    """盘中 9:25 选股调度器（外层封装，提供 wait_until_9_25 + run）。

    用法：
        runner = DailyRunner(l2_verify=True)
        runner.wait_until_trigger()  # 阻塞直到 09:25:01
        runner.run_once(today='2026-09-13')
    """

    def __init__(self, output_dir: str = DEFAULT_OUTPUT_DIR,
                 l2_verify: bool = L2_VERIFY_DEFAULT,
                 l2_fetcher: Optional[L2QuoteFetcher] = None,
                 l2_weights: tuple = L2_WEIGHTS_DEFAULT):
        self.output_dir = output_dir
        self.l2_verify = l2_verify
        self.l2_fetcher = l2_fetcher
        self.l2_weights = l2_weights

    @staticmethod
    def next_9_25(now: datetime = None) -> datetime:
        """返回今日（或明日）09:25:01 的 datetime。"""
        now = now or datetime.now()
        target = now.replace(hour=9, minute=25, second=1, microsecond=0)
        if target <= now:
            target = target + timedelta(days=1)
        # 跳过周末
        while target.weekday() >= 5:
            target = target + timedelta(days=1)
        return target

    def wait_until_trigger(self) -> None:
        """阻塞直到下一个 09:25:01（工作日）。"""
        target = self.next_9_25()
        wait = (target - datetime.now()).total_seconds()
        print(f"[DailyRunner] 等到 {target.strftime('%Y-%m-%d %H:%M:%S')} "
              f"（{wait:.0f}s）")
        time.sleep(max(wait, 0))

    def run_once(self, today: str = None,
                 best_param: Dict = None) -> Dict:
        return select_at_open(
            today=today, best_param=best_param,
            output_dir=self.output_dir, interactive_guard=False,
            l2_verify=self.l2_verify,
            l2_fetcher=self.l2_fetcher,
            l2_weights=self.l2_weights,
        )

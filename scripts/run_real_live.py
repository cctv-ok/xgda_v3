#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_real_live.py：盘中 9:25 真实选股入口

用法：
    1. 阻塞等到 09:25:01 后自动跑：
       python scripts/run_real_live.py
    2. 立即跑（覆盖时序检查）：
       python scripts/run_real_live.py --once
    3. dry-run（mock 数据，验证链路）：
       python scripts/run_real_live.py --dry
    4. 启用 L2 实时盘口二次校验（需通达信客户端已挂载 nbcomte.dat 并提供 7709 TCP）：
       python scripts/run_real_live.py --once --l2-verify
       python scripts/run_real_live.py --dry  --l2-verify
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def main():
    parser = argparse.ArgumentParser(description="XGDA Real 9:25 盘中选股")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--once", action="store_true",
                       help="立即跑选股，覆盖 9:25 时序检查")
    group.add_argument("--dry", action="store_true",
                       help="dry-run（mock 数据，不读 TDX）")
    parser.add_argument("--output-dir", default="output",
                        help="输出目录（默认 output/）")
    parser.add_argument("--l2-verify", action="store_true",
                        help="启用 L2 实时盘口二次校验"
                             "（需通达信客户端已挂 L2 站点并开放 7709 TCP）")
    parser.add_argument("--tdx-host", default="127.0.0.1",
                        help="TDX TCP 主机（默认 127.0.0.1）")
    parser.add_argument("--tdx-port", type=int, default=7709,
                        help="TDX TCP 端口（默认 7709）")
    parser.add_argument("--xg-weight", type=float, default=0.6,
                        help="XGDA 权重（默认 0.6，L2 权重 = 1-xg-weight）")
    args = parser.parse_args()

    if args.dry:
        from xgda.real import select_at_open, load_best_param
        from xgda.data_source import load_data, make_l2_fetcher
        from xgda.config import RESULT_CSV_TRAIN
        import pandas as pd

        print("[run_real_live --dry] 开始 dry-run…")
        mock_df = load_data(mode="mock", n_stocks=20, n_days=120)
        mock_df["datetime"] = pd.to_datetime(mock_df["datetime"])
        today = mock_df["datetime"].max().strftime("%Y-%m-%d")
        best_param = load_best_param() or {
            "z_min": 10, "z_max": 100, "score": 0.5,
        }

        # 真实部署时：fetcher = TcpL2Fetcher(host=tdx_host, port=tdx_port) 之子类
        # dry-run 用 NoopL2Fetcher 验证链路
        fetcher = None
        if args.l2_verify:
            fetcher = make_l2_fetcher("noop")

        result = select_at_open(
            today=today, today_df=mock_df, best_param=best_param,
            output_dir=args.output_dir, interactive_guard=False,
            l2_verify=args.l2_verify, l2_fetcher=fetcher,
            l2_weights=(args.xg_weight, 1.0 - args.xg_weight),
        )
        print(f"[dry-run] ✓ 选出 {len(result['selected'])} 只 → "
              f"{result.get('output_json')}")
        print(f"  L2 active: {result.get('l2_active')}, "
              f"weights: {result.get('l2_weights')}")
        return

    if args.once:
        from xgda.real import select_at_open, load_best_param
        from xgda.data_source import load_tdx7, TcpL2Fetcher
        import pandas as pd

        print("[run_real_live --once] 读 tdx7 真实数据…")
        all_data = load_tdx7()
        best_param = load_best_param()
        if best_param is None:
            print("⚠️ train CSV 不存在，先跑训练：python -m xgda --data tdx7")
            return
        today = pd.Timestamp.now().strftime("%Y-%m-%d")

        fetcher = None
        if args.l2_verify:
            # ⚠️ 真实接入需要 cctv 在子类里实现 _send_recv_protocol()
            # 这里只暴露连接入口，避免误传"已对接"假象
            print("[--once --l2-verify]⚠️ TcpL2Fetcher 默认 _send_recv_protocol "
                  "抛 NotImplementedError，请先在子类里实现 pytdx/mootdx 协议层。")
            fetcher = TcpL2Fetcher(host=args.tdx_host, port=args.tdx_port)

        result = select_at_open(
            today=today, today_df=all_data, best_param=best_param,
            output_dir=args.output_dir, interactive_guard=False,
            l2_verify=args.l2_verify, l2_fetcher=fetcher,
            l2_weights=(args.xg_weight, 1.0 - args.xg_weight),
        )
        print(f"[once] ✓ 选出 {len(result['selected'])} 只 → "
              f"{result.get('output_json')}")
        return

    # 默认：阻塞等到 9:25 后自动跑
    from xgda.real import DailyRunner
    from xgda.data_source import TcpL2Fetcher
    fetcher = TcpL2Fetcher(host=args.tdx_host, port=args.tdx_port) \
        if args.l2_verify else None
    runner = DailyRunner(
        output_dir=args.output_dir,
        l2_verify=args.l2_verify, l2_fetcher=fetcher,
        l2_weights=(args.xg_weight, 1.0 - args.xg_weight),
    )
    runner.wait_until_trigger()
    runner.run_once()


if __name__ == "__main__":
    main()

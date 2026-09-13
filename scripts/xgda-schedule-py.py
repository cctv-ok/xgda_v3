#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""xgda-schedule-py.py: Python 定时调度（PowerShell 任务计划的 fallback）

为什么需要这个：
    * PowerShell `Register-ScheduledTask` 在某些环境（sandbox / 非交互 shell）
      会假成功（返回对象但任务不进 Windows Task Scheduler）。
    * 改用 Python 自带的 time + datetime 调度，零外部依赖、最稳定。

用法：
    python scripts/xgda-schedule-py.py --once           # 立即跑一次（不阻塞）
    python scripts/xgda-schedule-py.py                 # 阻塞等到 9:25:01 自动跑
    python scripts/xgda-schedule-py.py --at "09:25:00"  # 自定义时间
    python scripts/xgda-schedule-py.py --interval 60    # 每 60 秒检查一次（默认）
    python scripts/xgda-schedule-py.py --dry            # dry-run（mock 数据）
"""
import argparse
import sys
import time
from datetime import datetime, time as dtime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def log(msg: str, log_file: Path = None) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def parse_time(s: str) -> dtime:
    """解析 HH:MM:SS 字符串。"""
    parts = s.split(":")
    if len(parts) != 3:
        raise ValueError(f"time must be HH:MM:SS, got {s!r}")
    try:
        h, m, sec = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError as e:
        raise ValueError(f"time parts must be integers, got {s!r}: {e}")
    return dtime(h, m, sec)


def is_weekday(d: datetime) -> bool:
    """周一 ~ 周五 = 工作日（5 = Saturday, 6 = Sunday in weekday()）。"""
    return d.weekday() < 5


def seconds_until_next(target: dtime, now: datetime = None) -> float:
    """等到下次 target 时分（含跨日处理 + 跳过周末）。"""
    now = now or datetime.now()
    if not is_weekday(now):
        # 周末：跳到下周一 9:25
        days_ahead = 7 - now.weekday()  # weekday()=5,6 → 7-5=2, 7-6=1
        next_day = now.date() + timedelta(days=days_ahead)
        next_dt = datetime.combine(next_day, target)
        return (next_dt - now).total_seconds()

    today_target = datetime.combine(now.date(), target)
    if now < today_target:
        return (today_target - now).total_seconds()

    # 今天已过 → 下一个工作日
    next_day = now.date() + timedelta(days=1)
    while True:
        wd = next_day.weekday()
        if wd < 5:  # 工作日
            break
        next_day += timedelta(days=1)
    next_dt = datetime.combine(next_day, target)
    return (next_dt - now).total_seconds()


def run_xgda_live(args, log_file: Path) -> int:
    """调 run_real_live.py 跑 9:25 选股。"""
    import subprocess
    py = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if not py.exists():
        py = PROJECT_ROOT / ".venv" / "bin" / "python"

    cmd = [str(py), str(PROJECT_ROOT / "scripts" / "run_real_live.py")]
    if args.dry:
        cmd.append("--dry")
    else:
        cmd.append("--once")  # 非 dry 模式必走 --once
    if not args.no_l2:
        cmd.append("--l2-verify")
    if args.xg_weight is not None:
        cmd += ["--xg-weight", str(args.xg_weight)]

    log(f"[scheduler] launching: {' '.join(cmd)}", log_file)
    rc = subprocess.call(cmd, cwd=str(PROJECT_ROOT))
    log(f"[scheduler] subprocess exit code = {rc}", log_file)
    return rc


def main():
    parser = argparse.ArgumentParser(
        description="XGDA Python scheduler (fallback when PowerShell taskscheduler fails)"
    )
    parser.add_argument("--once", action="store_true",
                        help="立即跑一次（不阻塞等 9:25）")
    parser.add_argument("--dry", action="store_true",
                        help="dry-run（mock 数据）")
    parser.add_argument("--at", default="09:25:00",
                        help="目标时间 HH:MM:SS（默认 09:25:00）")
    parser.add_argument("--no-l2", action="store_true",
                        help="关闭 L2 验证")
    parser.add_argument("--xg-weight", type=float, default=None,
                        help="XGDA 权重")
    parser.add_argument("--interval", type=int, default=60,
                        help="检查间隔秒数（默认 60）")
    parser.add_argument("--log-file",
                        default=str(PROJECT_ROOT / "logs" / "xgda-schedule-py.log"))
    args = parser.parse_args()

    log_file = Path(args.log_file)
    target = parse_time(args.at)
    log(f"[scheduler] start, target={target}, interval={args.interval}s, "
        f"once={args.once}, dry={args.dry}", log_file)

    if args.once:
        rc = run_xgda_live(args, log_file)
        sys.exit(rc)

    # 阻塞循环
    while True:
        wait_sec = seconds_until_next(target)
        log(f"[scheduler] next run in {wait_sec:.0f}s "
            f"({wait_sec/3600:.1f}h) → {target}", log_file)
        # 分段 sleep（每 60s 醒来检查一次，支持 Ctrl+C 立即停）
        slept = 0.0
        while slept < wait_sec:
            chunk = min(args.interval, wait_sec - slept)
            try:
                time.sleep(chunk)
            except KeyboardInterrupt:
                log("[scheduler] KeyboardInterrupt, exit", log_file)
                sys.exit(0)
            slept += chunk
        # 到点了
        rc = run_xgda_live(args, log_file)
        if rc != 0:
            log(f"[scheduler] WARN run returned {rc}, but continue loop",
                log_file)


if __name__ == "__main__":
    main()
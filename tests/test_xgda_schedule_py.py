"""tests/test_xgda_schedule_py.py：xgda-schedule-py.py 全调度逻辑单测

测试矩阵（6 大块 / 50+ 用例）：
    1. parse_time  — HH:MM:SS 解析（含错误处理）
    2. is_weekday  — Mon-Fri vs Sat-Sun
    3. seconds_until_next  — 跨日/跨周末/午夜/年边界
    4. log  — stdout + 文件 append + 父目录自动创建
    5. run_xgda_live  — 子进程拼装 + exit code 透传
    6. main  — --once / --dry / --no-l2 / KeyboardInterrupt
"""
import importlib.util
import os
import sys
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from unittest import mock

import pytest

# 把 scripts/ 加进 sys.path 让 conftest 能找到；再 importlib 按文件路径加载
SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "xgda-schedule-py.py"
PROJECT_ROOT = SCRIPT_PATH.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

# 文件名有连字符（xgda-schedule-py.py），Python 标识符不接受，用 importlib 直加载
_spec = importlib.util.spec_from_file_location("xgda_schedule_py", str(SCRIPT_PATH))
sp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sp)
# 让其他测试代码能 `from xgda_schedule_py import PROJECT_ROOT`
sys.modules["xgda_schedule_py"] = sp


# =============================================================================
# 1. parse_time — HH:MM:SS 解析
# =============================================================================
class TestParseTime:
    def test_basic(self):
        assert sp.parse_time("09:25:00") == dtime(9, 25, 0)

    def test_midnight(self):
        assert sp.parse_time("00:00:00") == dtime(0, 0, 0)

    def test_end_of_day(self):
        assert sp.parse_time("23:59:59") == dtime(23, 59, 59)

    def test_close_time(self):
        # 集合竞价结束 09:30
        assert sp.parse_time("09:30:00") == dtime(9, 30, 0)

    def test_14pm(self):
        assert sp.parse_time("14:00:00") == dtime(14, 0, 0)

    def test_invalid_format_too_few_parts(self):
        with pytest.raises(ValueError):
            sp.parse_time("09:25")  # 缺秒

    def test_invalid_format_too_many_parts(self):
        with pytest.raises(ValueError):
            sp.parse_time("09:25:00:00")

    def test_invalid_format_non_numeric(self):
        with pytest.raises(ValueError):
            sp.parse_time("aa:bb:cc")

    def test_invalid_hour_range(self):
        # 24:00:00 解析 dtime 会溢出 → ValueError
        with pytest.raises(ValueError):
            sp.parse_time("24:00:00")

    def test_invalid_minute_range(self):
        with pytest.raises(ValueError):
            sp.parse_time("09:60:00")


# =============================================================================
# 2. is_weekday — 周一到周五为工作日
# =============================================================================
class TestIsWeekday:
    @pytest.mark.parametrize("date_str,expected", [
        ("2026-09-14", True),   # Mon
        ("2026-09-15", True),   # Tue
        ("2026-09-16", True),   # Wed
        ("2026-09-17", True),   # Thu
        ("2026-09-18", True),   # Fri
        ("2026-09-19", False),  # Sat
        ("2026-09-20", False),  # Sun
    ])
    def test_weekday_table(self, date_str, expected):
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        assert sp.is_weekday(dt) == expected


# =============================================================================
# 3. seconds_until_next — 调度核心时间算法
# =============================================================================
class TestSecondsUntilNext:
    TARGET = dtime(9, 25, 0)

    # ---- 今天是工作日 ----

    def test_today_future(self):
        # 今天 09:00 → 等到 09:25 → 25 分钟 = 1500s
        now = datetime(2026, 9, 14, 9, 0, 0)  # Mon 09:00
        sec = sp.seconds_until_next(self.TARGET, now)
        assert sec == 1500.0

    def test_today_just_before_target(self):
        # 今天 09:24:30 → 30 秒后
        now = datetime(2026, 9, 14, 9, 24, 30)
        sec = sp.seconds_until_next(self.TARGET, now)
        assert sec == 30.0

    def test_today_just_after_target(self):
        # 今天 09:25:01 → 跳到明天 09:25:00（~23h59m59s）
        now = datetime(2026, 9, 14, 9, 25, 1)
        sec = sp.seconds_until_next(self.TARGET, now)
        assert 23 * 3600 < sec < 24 * 3600

    def test_today_late_evening(self):
        # 今天 17:30 → 明天 09:25（约 15h55m）
        now = datetime(2026, 9, 14, 17, 30, 0)
        sec = sp.seconds_until_next(self.TARGET, now)
        assert sec == pytest.approx((9 * 3600 + 25 * 60) - (17 * 3600 + 30 * 60) + 24 * 3600)

    def test_friday_after_target_to_monday(self):
        # 周五 09:30 → 跳到下周一 09:25（~71h55m）
        now = datetime(2026, 9, 18, 9, 30, 0)  # Fri 09:30
        sec = sp.seconds_until_next(self.TARGET, now)
        # Fri 09:30 → Mon 09:25 = 3 天 - 5 分钟 = 72h - 5m = 258900s（跨周六周日）
        assert sec == pytest.approx(3 * 86400 - 5 * 60)

    def test_friday_before_target(self):
        # 周五 09:00 → 今天 09:25（25 分钟）
        now = datetime(2026, 9, 18, 9, 0, 0)
        sec = sp.seconds_until_next(self.TARGET, now)
        assert sec == 1500.0

    # ---- 今天是周末 → 跳到下周一 ----

    def test_saturday_to_monday(self):
        # 周六 12:00 → 周一 09:25（约 45h25m）
        now = datetime(2026, 9, 19, 12, 0, 0)  # Sat 12:00
        sec = sp.seconds_until_next(self.TARGET, now)
        # Sat 12:00 → Mon 09:25 = 1d21h25m = 164700s
        assert sec == pytest.approx(1 * 86400 + 21 * 3600 + 25 * 60)

    def test_sunday_to_monday(self):
        # 周日 12:00 → 周一 09:25（约 21h25m）
        now = datetime(2026, 9, 20, 12, 0, 0)  # Sun 12:00
        sec = sp.seconds_until_next(self.TARGET, now)
        # Sun 12:00 → Mon 09:25 = 21h25m = 77100s
        assert sec == pytest.approx(21 * 3600 + 25 * 60)

    def test_saturday_morning_to_monday(self):
        # 周六 00:00 → 周一 09:25（约 57h25m）
        now = datetime(2026, 9, 19, 0, 0, 0)  # Sat 00:00
        sec = sp.seconds_until_next(self.TARGET, now)
        # Sat 00:00 → Mon 09:25 = 2d9h25m = 201900s
        assert sec == pytest.approx(2 * 86400 + 9 * 3600 + 25 * 60)

    # ---- 自定义 target_time（边界）----

    def test_custom_target_midnight(self):
        # target = 00:00:00，今天 23:59 → 1 分钟后
        target = dtime(0, 0, 0)
        now = datetime(2026, 9, 14, 23, 59, 0)
        sec = sp.seconds_until_next(target, now)
        assert sec == pytest.approx(60.0)

    def test_custom_target_afternoon(self):
        # target = 14:00，今天 13:00 → 1h
        target = dtime(14, 0, 0)
        now = datetime(2026, 9, 14, 13, 0, 0)
        sec = sp.seconds_until_next(target, now)
        assert sec == pytest.approx(3600.0)

    def test_custom_target_evening(self):
        # target = 22:00，今天 09:00 → 13h
        target = dtime(22, 0, 0)
        now = datetime(2026, 9, 14, 9, 0, 0)
        sec = sp.seconds_until_next(target, now)
        assert sec == pytest.approx(13 * 3600.0)

    # ---- 年边界 ----

    def test_year_boundary(self):
        # 2026/12/31 (Thu) 10:00 → 2027/01/01 (Fri) 09:25
        now = datetime(2026, 12, 31, 10, 0, 0)
        sec = sp.seconds_until_next(self.TARGET, now)
        # Thu 10:00 → Fri 09:25 = 23h25m = 84300s
        assert sec == pytest.approx(23 * 3600 + 25 * 60)

    def test_year_boundary_via_friday(self):
        # 2026/12/31 是周四 → Thu 10:00 → Fri 09:25
        # 验证跨年 weekday 正确
        now = datetime(2026, 12, 31, 10, 0, 0)
        assert sp.is_weekday(now) is True
        sec = sp.seconds_until_next(self.TARGET, now)
        assert sec > 0

    # ---- None 输入 → 用 datetime.now() ----

    def test_none_means_now(self):
        # 不能精确测，但能保证不抛异常
        sec = sp.seconds_until_next(self.TARGET)
        assert sec > 0
        assert sec < 7 * 86400  # 7 天内必有下次触发

    # ---- 周一→周二 周间边界 ----

    def test_monday_evening_to_tuesday(self):
        # 周一 22:00 → 周二 09:25（11h25m）
        now = datetime(2026, 9, 14, 22, 0, 0)  # Mon 22:00
        sec = sp.seconds_until_next(self.TARGET, now)
        assert sec == pytest.approx(11 * 3600 + 25 * 60)


# =============================================================================
# 4. log — stdout + 文件落档
# =============================================================================
class TestLog:
    def test_prints_to_stdout(self, capsys):
        sp.log("hello world", log_file=None)
        captured = capsys.readouterr()
        assert "hello world" in captured.out
        # 含 ISO 时间戳前缀
        import re
        assert re.match(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] hello world",
                        captured.out.strip())

    def test_appends_to_file(self, tmp_path):
        log_file = tmp_path / "log.txt"
        sp.log("line1", log_file=log_file)
        sp.log("line2", log_file=log_file)
        content = log_file.read_text(encoding="utf-8")
        lines = content.strip().split("\n")
        assert len(lines) == 2
        assert "line1" in lines[0]
        assert "line2" in lines[1]

    def test_creates_parent_dir(self, tmp_path):
        log_file = tmp_path / "deep" / "nested" / "log.txt"
        assert not log_file.parent.exists()
        sp.log("hi", log_file=log_file)
        assert log_file.parent.exists()
        assert log_file.read_text(encoding="utf-8").strip().endswith("hi")

    def test_no_file_no_crash(self, capsys):
        sp.log("no-file mode")
        captured = capsys.readouterr()
        assert "no-file mode" in captured.out

    def test_unicode(self, tmp_path):
        """中文 / emoji 也能正确编码（UTF-8 文件）。"""
        log_file = tmp_path / "log.txt"
        sp.log("启动 → ✓", log_file=log_file)
        content = log_file.read_text(encoding="utf-8")
        assert "启动" in content
        assert "✓" in content

    def test_default_log_file_path(self):
        """默认 log_file 路径应可解析（不要求真存在）。"""
        from xgda_schedule_py import PROJECT_ROOT
        default = PROJECT_ROOT / "logs" / "xgda-schedule-py.log"
        # 不调用，只确认路径可构造
        assert default.parent.name == "logs"
        assert default.name == "xgda-schedule-py.log"


# =============================================================================
# 5. run_xgda_live — 子进程拼装 + exit code 透传
# =============================================================================
class TestRunXgdaLive:
    @pytest.fixture
    def mock_args(self):
        """构造 argparse Namespace 等价物。"""

        class Args:
            dry = False
            no_l2 = False
            xg_weight = None
        return Args()

    @pytest.fixture
    def log_file(self, tmp_path):
        return tmp_path / "log.txt"

    def _expected_python(self):
        # 项目里 .venv\Scripts\python.exe 或 .venv/bin/python
        for cand in [PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",
                     PROJECT_ROOT / ".venv" / "bin" / "python"]:
            if cand.exists():
                return str(cand)
        return str(cand)  # fallback 任一

    def test_dry_runs_with_dry_flag(self, mock_args, log_file):
        mock_args.dry = True
        with mock.patch("subprocess.call", return_value=0) as mc:
            rc = sp.run_xgda_live(mock_args, log_file)
        assert rc == 0
        cmd = mc.call_args[0][0]
        assert "--dry" in cmd
        assert "--once" not in cmd  # dry 模式不加 --once

    def test_real_runs_with_once(self, mock_args, log_file):
        # mock_args.dry = False（默认）
        with mock.patch("subprocess.call", return_value=0) as mc:
            rc = sp.run_xgda_live(mock_args, log_file)
        assert rc == 0
        cmd = mc.call_args[0][0]
        assert "--once" in cmd
        assert "--dry" not in cmd

    def test_l2_verify_added_by_default(self, mock_args, log_file):
        with mock.patch("subprocess.call", return_value=0) as mc:
            sp.run_xgda_live(mock_args, log_file)
        cmd = mc.call_args[0][0]
        assert "--l2-verify" in cmd

    def test_no_l2_flag_removes_l2_verify(self, mock_args, log_file):
        mock_args.no_l2 = True
        with mock.patch("subprocess.call", return_value=0) as mc:
            sp.run_xgda_live(mock_args, log_file)
        cmd = mc.call_args[0][0]
        assert "--l2-verify" not in cmd

    def test_xg_weight_passed(self, mock_args, log_file):
        mock_args.xg_weight = 0.7
        with mock.patch("subprocess.call", return_value=0) as mc:
            sp.run_xgda_live(mock_args, log_file)
        cmd = mc.call_args[0][0]
        assert "--xg-weight" in cmd
        i = cmd.index("--xg-weight")
        assert cmd[i + 1] == "0.7"

    def test_no_xg_weight_omits_flag(self, mock_args, log_file):
        mock_args.xg_weight = None
        with mock.patch("subprocess.call", return_value=0) as mc:
            sp.run_xgda_live(mock_args, log_file)
        cmd = mc.call_args[0][0]
        assert "--xg-weight" not in cmd

    def test_exit_code_propagates(self, mock_args, log_file):
        """子进程非 0 退出码应原样返回。"""
        with mock.patch("subprocess.call", return_value=42):
            rc = sp.run_xgda_live(mock_args, log_file)
        assert rc == 42

    def test_cwd_is_project_root(self, mock_args, log_file):
        with mock.patch("subprocess.call", return_value=0) as mc:
            sp.run_xgda_live(mock_args, log_file)
        cwd = mc.call_args[1]["cwd"]
        assert cwd == str(PROJECT_ROOT)

    def test_logs_launch_and_exit(self, mock_args, log_file):
        with mock.patch("subprocess.call", return_value=5):
            sp.run_xgda_live(mock_args, log_file)
        content = log_file.read_text(encoding="utf-8")
        assert "[scheduler] launching:" in content
        assert "exit code = 5" in content


# =============================================================================
# 6. main() — 集成路径
# =============================================================================
class TestMain:
    """通过 `python -c "import sys; sys.argv=...; sp.main()"` 调 main()"""

    @pytest.fixture(autouse=True)
    def reset_argv(self):
        """每个测试前后清 argv。"""
        original = sys.argv[:]
        yield
        sys.argv = original

    def _run_main(self, *args):
        """跑 main() 并捕获 SystemExit。"""
        sys.argv = ["xgda-schedule-py.py"] + list(args)
        try:
            sp.main()
        except SystemExit as e:
            return e.code

    def test_once_runs_and_exits_zero(self, tmp_path):
        """--once 模式：调一次 run_xgda_live 后退出。"""
        with mock.patch.object(sp, "run_xgda_live", return_value=0) as mrl:
            rc = self._run_main("--once",
                                "--log-file", str(tmp_path / "log.txt"))
        assert mrl.call_count == 1
        assert rc == 0

    def test_once_propagates_subprocess_rc(self, tmp_path):
        with mock.patch.object(sp, "run_xgda_live", return_value=42):
            rc = self._run_main("--once",
                                "--log-file", str(tmp_path / "log.txt"))
        assert rc == 42

    def test_dry_flag_passes_through(self, tmp_path):
        with mock.patch.object(sp, "run_xgda_live", return_value=0) as mrl:
            self._run_main("--once", "--dry",
                           "--log-file", str(tmp_path / "log.txt"))
        call_args = mrl.call_args[0][0]
        assert call_args.dry is True

    def test_no_l2_flag_passes_through(self, tmp_path):
        with mock.patch.object(sp, "run_xgda_live", return_value=0) as mrl:
            self._run_main("--once", "--no-l2",
                           "--log-file", str(tmp_path / "log.txt"))
        call_args = mrl.call_args[0][0]
        assert call_args.no_l2 is True

    def test_xg_weight_passes_through(self, tmp_path):
        with mock.patch.object(sp, "run_xgda_live", return_value=0) as mrl:
            self._run_main("--once", "--xg-weight", "0.8",
                           "--log-file", str(tmp_path / "log.txt"))
        call_args = mrl.call_args[0][0]
        assert call_args.xg_weight == 0.8

    def test_default_at_is_0925(self, tmp_path):
        with mock.patch.object(sp, "run_xgda_live", return_value=0):
            self._run_main("--once",
                           "--log-file", str(tmp_path / "log.txt"))
        log_content = (tmp_path / "log.txt").read_text(encoding="utf-8")
        assert "target=09:25:00" in log_content

    def test_custom_at_overrides(self, tmp_path):
        with mock.patch.object(sp, "run_xgda_live", return_value=0):
            self._run_main("--once", "--at", "14:00:00",
                           "--log-file", str(tmp_path / "log.txt"))
        log_content = (tmp_path / "log.txt").read_text(encoding="utf-8")
        assert "target=14:00:00" in log_content

    def test_keyboard_interrupt_exits_zero(self, tmp_path):
        """阻塞循环里 Ctrl+C 应优雅退出 0。"""
        with mock.patch("time.sleep",
                        side_effect=KeyboardInterrupt):
            rc = self._run_main(
                "--interval", "1",
                "--at", "23:59:59",  # 远未来，强制进 sleep
                "--log-file", str(tmp_path / "log.txt"),
            )
        assert rc == 0
        log_content = (tmp_path / "log.txt").read_text(encoding="utf-8")
        assert "KeyboardInterrupt" in log_content

    def test_loop_continues_after_subprocess_failure(self, tmp_path):
        """子进程非 0 → 警告但继续循环（验证循环不会因 rc!=0 退出）。"""
        # 第 1 次调 seconds_until_next 返回 0（立即触发 run_xgda_live）
        # 第 2 次调 seconds_until_next 返回 1（进 sleep，fake_sleep 触发 KI）
        with mock.patch.object(sp, "seconds_until_next",
                               side_effect=[0, 1.0]):
            with mock.patch("time.sleep",
                            side_effect=KeyboardInterrupt):
                with mock.patch.object(sp, "run_xgda_live", return_value=99):
                    rc = self._run_main(
                        "--interval", "1",
                        "--at", "23:59:59",
                        "--log-file", str(tmp_path / "log.txt"),
                    )
        assert rc == 0  # KeyboardInterrupt 路径退出 0
        log_content = (tmp_path / "log.txt").read_text(encoding="utf-8")
        # 应记录 WARN + 继续循环
        assert "WARN run returned 99" in log_content
        assert "KeyboardInterrupt" in log_content

    def test_log_file_default_under_project_logs(self, tmp_path, monkeypatch):
        """不传 --log-file 时默认落 PROJECT_ROOT/logs/xgda-schedule-py.log。"""
        log_file = PROJECT_ROOT / "logs" / "xgda-schedule-py.log"
        if log_file.exists():
            log_file.unlink()
        monkeypatch.chdir(tmp_path)  # 避免污染项目目录

        with mock.patch.object(sp, "run_xgda_live", return_value=0):
            self._run_main("--once")
        assert log_file.exists()
        log_file.unlink()


# =============================================================================
# 7. 端到端 — 真跑 subprocess 调用 run_real_live.py --dry
# =============================================================================
class TestEndToEnd:
    """实际 spawn 子进程跑一次，验证链路真通。"""

    def test_dry_run_real_subprocess(self, tmp_path):
        log_file = tmp_path / "log.txt"
        sys.argv = ["xgda-schedule-py.py", "--once", "--dry",
                    "--log-file", str(log_file)]
        try:
            sp.main()
        except SystemExit as e:
            rc = e.code
        # dry-run 不依赖 tdx7 + l2 → exit 0
        assert rc == 0
        log_content = log_file.read_text(encoding="utf-8")
        assert "[scheduler] launching:" in log_content
        assert "--dry" in log_content
        assert "exit code = 0" in log_content

    def test_help_message(self, capsys):
        """--help 应展示 usage 且 exit 0。"""
        sys.argv = ["xgda-schedule-py.py", "--help"]
        try:
            sp.main()
        except SystemExit as e:
            rc = e.code
        assert rc == 0  # argparse --help 走 sys.exit(0)
        captured = capsys.readouterr()
        assert "XGDA Python scheduler" in captured.out
        assert "--once" in captured.out
        assert "--at" in captured.out
        assert "--interval" in captured.out
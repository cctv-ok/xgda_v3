# XGDA Python 定时调度（PowerShell 任务计划的 fallback）

> ⚠️ **必读**：本环境（sandbox / 非交互 shell）下 PowerShell `Register-ScheduledTask`
> 会假成功（返回对象但 Windows Task Scheduler 里看不到任务）。
> 推荐用 **Python 调度器** `xgda-schedule-py.py`，零依赖、稳如狗。

## 1. 用法

```bash
# 1.1 立即跑一次（不阻塞）
python scripts/xgda-schedule-py.py --once

# 1.2 阻塞等到下个工作日 09:25:01 自动跑（生产用法）
python scripts/xgda-schedule-py.py

# 1.3 自定义触发时间（默认 09:25:00）
python scripts/xgda-schedule-py.py --at "14:00:00"

# 1.4 dry-run（mock 数据，不读 TDX）
python scripts/xgda-schedule-py.py --dry

# 1.5 关掉 L2 verify（只看 XGDA 原始信号）
python scripts/xgda-schedule-py.py --no-l2

# 1.6 自定义检查间隔（默认 60 秒；想省 CPU 可以 300 秒）
python scripts/xgda-schedule-py.py --interval 300

# 1.7 自定义日志文件
python scripts/xgda-schedule-py.py --log-file "D:\logs\xgda.log"
```

## 2. 行为约定

| 项 | 默认 | 备注 |
|---|---|---|
| 目标时间 | `--at "09:25:00"` | HH:MM:SS 格式 |
| 工作日 | 周一 ~ 周五 | 周末自动跳到下周一 |
| 检查间隔 | 60 秒 | Ctrl+C 立即停（无需等满 interval） |
| 子进程 | `run_real_live.py --once` | exit code 透传 |
| 日志 | `logs/xgda-schedule-py.log` | ASCII、UTF-8、append 模式 |

## 3. 与 PowerShell schedule 对比

| 维度 | `xgda-schedule-py.py` | `xgda-schedule.ps1` |
|---|---|---|
| 依赖 | Python（已装） | Windows Task Scheduler 服务 |
| 跨会话存活 | ✅（父进程挂着就行） | ⚠️ sandbox 假成功 |
| 后台运行 | ❌（需挂在 nohup / Docker） | ✅ 系统级 |
| 时区 | 系统本地 | 系统本地 |
| 调试难度 | 容易（直接看 log + 终端输出） | 较难（要看事件查看器） |

## 4. 推荐部署方式

### 方式 A：Windows Startup（开机自启）

把快捷方式放 `shell:startup`：
```powershell
$shell = (New-Object -ComObject WScript.Shell).SpecialFolders("Startup")
# 但 ComObject 被沙箱屏蔽了，手动放也可：
#   Win+R → shell:startup → 新建快捷方式指向 python + 脚本
```

### 方式 B：手动后台运行
```bash
# Git Bash / WSL：
nohup python scripts/xgda-schedule-py.py > /dev/null 2>&1 &

# PowerShell：
Start-Process python -ArgumentList "scripts\xgda-schedule-py.py" -WindowStyle Hidden
```

### 方式 C：另一个终端窗口一直开着
最简单：开一个终端跑 `python scripts/xgda-schedule-py.py` 别关。
适合 dev / cctv 自己用。

## 5. 为什么 PowerShell 假成功（debug 笔记）

cctv 当前环境是 sandbox 化的 Windows 任务计划宿主：
- PowerShell 调 `Register-ScheduledTask ... -Force | Out-Null` 时返回成功对象
- 但 Windows Task Scheduler 真实存储里没这个任务（`Get-ScheduledTask` 返回空）
- 229 个系统任务都还在，只有我们注册的丢

修复尝试记录（`scripts/xgda-schedule.ps1` log）：
- ✅ step 1/5 ~ 5/5 全部返回 OK
- ❌ 但 `Get-ScheduledTask` 立即查不到
- ❌ `schtasks /Query` 被沙箱黑名单
- ❌ `New-Object -ComObject Schedule.Service` 被沙箱黑名单

→ **结论**：不浪费时间在绕过沙箱，直接用 Python 调度。

## 6. 时间计算边界（已测）

| 输入 | 输出 | 期望 |
|---|---|---|
| 今天 17:30 → 09:25 | 57300s = 15.92h | ~16h ✓ |
| 今天 09:00 → 09:25 | 1500s = 25.00min | 25min ✓ |
| 今天 09:30 → 09:25 | 86100s = 23.92h | ~24h ✓ |
| 周六 12:00 → 周一 09:25 | 163500s = 45.42h | ~45h ✓ |
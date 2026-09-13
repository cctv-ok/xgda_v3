@echo off
REM ============================================================
REM XGDA 一键 dry-run 链路验证（无需通达信客户端）
REM
REM 用法：
REM   scripts\xgda-dryrun.bat                    默认（开 L2 verify）
REM   scripts\xgda-dryrun.bat --no-l2            关闭 L2 验证
REM   scripts\xgda-dryrun.bat --xg-weight 0.7    调整 XGDA 权重（0-1）
REM
REM 落点：
REM   - 阻塞等待时间: 无
REM   - 数据源: mock（程序生成 20 只票 × 120 日）
REM   - L2:  默认 NoopL2Fetcher（仅链路验证，不连真实 L2）
REM   - 输出: output\select_YYYY-MM-DD_HHMMSS.{json,txt}
REM ============================================================

setlocal EnableDelayedExpansion
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%.."

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [xgda-dryrun] ERROR: 找不到 %PY%
    echo                  请先创建 venv：python -m venv .venv ^&^& .venv\Scripts\python -m pip install -r requirements.txt
    popd
    exit /b 1
)

REM 参数清洗：脚本层只接受 --no-l2 / --xg-weight N，其余透传
set "L2_FLAG=--l2-verify"
set "FORWARD_ARGS="
:parse_args
if "%~1"=="" goto :after_parse
if /I "%~1"=="--no-l2" (
    set "L2_FLAG="
    shift
    goto :parse_args
)
if /I "%~1"=="--l2-verify" (
    REM 显式指定与默认值一致，忽略
    shift
    goto :parse_args
)
set "FORWARD_ARGS=!FORWARD_ARGS! %~1"
shift
goto :parse_args
:after_parse

echo [xgda-dryrun] 开始 mock 链路验证...
echo [xgda-dryrun] Python: %CD%\%PY%
echo [xgda-dryrun] L2 标志: !L2_FLAG!
echo.

"%PY%" scripts\run_real_live.py --dry !L2_FLAG! !FORWARD_ARGS!

set "RC=%ERRORLEVEL%"
echo.
echo [xgda-dryrun] 退出码 %RC%
popd
exit /b %RC%


@echo off
REM ============================================================
REM XGDA 一键真 9:25 跑（需通达信客户端挂载 L2 站点）
REM
REM 用法：
REM   scripts\xgda-live.bat                          阻塞等到今日 09:25:01
REM   scripts\xgda-live.bat --once                   立即跑（覆盖时序检查）
REM   scripts\xgda-live.bat --once --no-l2           关闭 L2 校验
REM   scripts\xgda-live.bat --xg-weight 0.7          调整 XGDA 权重
REM
REM 落点：
REM   - 数据源: D:\tdx7\*.csv
REM   - L2:     默认 NoopL2Fetcher；生产前需 cctv 在子类实现协议层
REM   - 输出:   output\select_YYYY-MM-DD_HHMMSS.{json,txt}
REM ============================================================

setlocal
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%.."

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [xgda-live] ERROR: 找不到 %PY%
    popd
    exit /b 1
)

echo [xgda-live] 启动...
echo [xgda-live] Python: %CD%\%PY%
echo [xgda-live] 当前时间: %DATE% %TIME%
echo [xgda-live] 参数透传: %*
echo.

"%PY%" scripts\run_real_live.py --once --l2-verify %*

set "RC=%ERRORLEVEL%"
echo.
echo [xgda-live] 退出码 %RC%
popd
exit /b %RC%

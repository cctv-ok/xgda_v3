@echo off
REM ============================================================
REM XGDA 9:25 定时调度（Windows 任务计划）
REM
REM 用法：
REM   scripts\xgda-schedule.bat install    安装工作日 09:25 定时任务
REM   scripts\xgda-schedule.bat uninstall  卸载定时任务
REM   scripts\xgda-schedule.bat status     查看任务状态
REM ============================================================

setlocal
set "TASK_NAME=XGDA_0925_RealSelect"
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%.."

set "PY=%CD%\.venv\Scripts\python.exe"
set "SCRIPT=%CD%\scripts\xgda-live.bat"

if not exist "%PY%" (
    echo [schedule] ERROR: 找不到 %PY%
    popd
    exit /b 1
)

if /I "%1"=="install" goto :install
if /I "%1"=="uninstall" goto :uninstall
if /I "%1"=="status" goto :status

echo 用法: %~nx0 install ^| uninstall ^| status
popd
exit /b 1

:install
echo [schedule] 安装工作日 09:25 定时任务...
schtasks /Create /SC WEEKLY /D MON,TUE,WED,THU,FRI /TN "%TASK_NAME%" ^
    /TR "\"%SCRIPT%\"" /ST 09:25:00 /F
if errorlevel 1 (
    echo [schedule] ERROR: schtasks /Create 失败
    popd
    exit /b 1
)
echo [schedule] ✓ 已安装: %TASK_NAME%
echo   触发: 工作日 09:25:00
echo   命令: %SCRIPT%
goto :end

:uninstall
echo [schedule] 卸载定时任务...
schtasks /Delete /TN "%TASK_NAME%" /F
if errorlevel 1 (
    echo [schedule] 任务不存在或已卸载
    goto :end
)
echo [schedule] ✓ 已卸载
goto :end

:status
schtasks /Query /TN "%TASK_NAME%" /V /FO LIST 2>nul
if errorlevel 1 (
    echo [schedule] 任务 %TASK_NAME% 不存在
)
goto :end

:end
popd
endlocal

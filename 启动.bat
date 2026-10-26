@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 默认只监听本机；带参数 lan 启动时开放给同 WiFi 的手机 / 平板
if /i "%~1"=="lan" set "HOST=lan"

set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  if exist "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe" (
    set "PY=%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe"
  )
)
if not defined PY (
  echo [ERROR] Python not found. Please install Python 3.9+ first.
  pause
  exit /b 1
)

if /i "%~1"=="lan" (
  echo Mode: LAN - phone / tablet on the same WiFi can subscribe
) else (
  echo Mode: local only - run "start lan" ^(or set HOST=lan^) to allow phone access
)
echo Address: http://127.0.0.1:8899/
echo Keep this window open. Close it to stop the service.
echo.
start "" http://127.0.0.1:8899/
"%PY%" server.py
pause

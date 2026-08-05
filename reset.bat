@echo off
rem ============================================================
rem  Development-only reset. Never shipped in the zip.
rem
rem  KEEP THIS FILE PURE ASCII, INCLUDING ITS FILENAME.
rem  All Chinese text and all the actual delete logic live in
rem  reset_dev_data.py on purpose. Under chcp 65001, cmd.exe seeks
rem  by BYTE offset while counting CHARACTERS, so a .bat file with
rem  much Chinese in it eventually reads from the wrong position and
rem  starts EXECUTING its own text as commands. An earlier version of
rem  this file did exactly that and overwrote the live config.json.
rem  Python has no such problem, so the .bat stays a thin launcher.
rem ============================================================
setlocal
pushd "%~dp0"
python "%~dp0reset_dev_data.py" %*
set "RC=%ERRORLEVEL%"
popd
if /i "%~1"=="/Y" exit /b %RC%
echo.
pause
exit /b %RC%

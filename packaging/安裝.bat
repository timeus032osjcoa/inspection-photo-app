@echo off
if not defined UTF8_INSTALLER (
    chcp 65001 >nul
    set UTF8_INSTALLER=1
    cmd /c "%~f0"
    exit /b
)
title 工地照片系統 - 安裝精靈

echo ====================================================
echo   工地照片標記與報告系統 - 安裝精靈
echo ====================================================
echo.

rem ---- 1. 檢查 Python ----
where python >nul 2>nul
if errorlevel 1 goto :no_python

echo [OK] 偵測到 Python：
python --version
echo.
goto :ask_dest

:no_python
echo [注意] 偵測不到 Python，請先安裝 Python 3.10 以上版本：
echo     https://www.python.org/downloads/
echo     安裝畫面最下面記得勾選 "Add python.exe to PATH"，再按安裝。
echo.
echo 安裝完 Python 後，請重新雙擊這個「安裝.bat」。
start https://www.python.org/downloads/
pause
exit /b 1

rem ---- 2. 詢問安裝位置 ----
:ask_dest
set "DEFAULT_DEST=%USERPROFILE%\Desktop\工地照片系統"
set /p DEST="請輸入要安裝在哪個資料夾（直接按 Enter 使用預設： %DEFAULT_DEST% ）： "
if "%DEST%"=="" set "DEST=%DEFAULT_DEST%"

if not exist "%DEST%" goto :make_dirs

echo.
echo [注意] 資料夾 "%DEST%" 已經存在。
set /p CONFIRM="要繼續安裝到這個資料夾嗎？裡面同名的程式檔會被更新，但已經有的照片/資料不會被刪除 (Y/N)： "
if /i "%CONFIRM%"=="Y" goto :make_dirs

echo 已取消安裝。
pause
exit /b 0

:make_dirs
echo.
echo 正在建立資料夾...
mkdir "%DEST%" 2>nul
mkdir "%DEST%\incoming" 2>nul
mkdir "%DEST%\sorted" 2>nul
mkdir "%DEST%\output" 2>nul

echo 正在複製程式檔...
set "SRC=%~dp0"
copy /Y "%SRC%app.py" "%DEST%\" >nul
copy /Y "%SRC%mobile_app.py" "%DEST%\" >nul
copy /Y "%SRC%utils.py" "%DEST%\" >nul
copy /Y "%SRC%generate_report.py" "%DEST%\" >nul
copy /Y "%SRC%control_panel.py" "%DEST%\" >nul
copy /Y "%SRC%requirements.txt" "%DEST%\" >nul
copy /Y "%SRC%說明.txt" "%DEST%\" >nul
copy /Y "%SRC%README.md" "%DEST%\" >nul
copy /Y "%SRC%README_zh.md" "%DEST%\" >nul
copy /Y "%SRC%工地照片系統.bat" "%DEST%\" >nul

if exist "%DEST%\config.json" goto :config_exists
copy /Y "%SRC%config.json" "%DEST%\config.json" >nul
goto :setup_venv

:config_exists
echo [i] 偵測到已經有 config.json，保留原本的設定不覆蓋。

rem ---- 3. 建立虛擬環境並安裝套件 ----
:setup_venv
echo.
echo 正在建立獨立的 Python 執行環境並安裝套件（第一次安裝可能要一兩分鐘，請耐心等候）...
pushd "%DEST%"
python -m venv venv
if errorlevel 1 goto :venv_fail

call venv\Scripts\activate.bat
pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto :pip_fail

popd

echo.
echo ====================================================
echo   安裝完成！
echo ====================================================
echo.
echo 已安裝到：%DEST%
echo.
echo 打開那個資料夾，雙擊「工地照片系統.bat」就會開啟控制台，
echo 詳細操作說明在同一個資料夾裡的「說明.txt」。
echo.
pause
exit /b 0

:venv_fail
echo [注意] 建立 Python 執行環境失敗，請確認 Python 有安裝成功後再重新執行這個安裝檔。
popd
pause
exit /b 1

:pip_fail
echo [注意] 套件安裝失敗，請檢查網路連線後重新雙擊這個安裝檔重試一次。
popd
pause
exit /b 1

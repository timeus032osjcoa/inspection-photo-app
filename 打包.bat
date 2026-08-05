@echo off
if not defined UTF8_PACKAGER (
    chcp 65001 >nul
    set UTF8_PACKAGER=1
    cmd /c "%~f0"
    exit /b
)
title 打包成可以分享給別人的安裝包
setlocal

set "ROOT=%~dp0"
set "OUT=%ROOT%distribute"

echo 正在打包成可以分享給別人的安裝包...
echo.

if exist "%OUT%" rmdir /s /q "%OUT%"
mkdir "%OUT%"

copy /Y "%ROOT%app.py" "%OUT%\" >nul
copy /Y "%ROOT%mobile_app.py" "%OUT%\" >nul
copy /Y "%ROOT%utils.py" "%OUT%\" >nul
copy /Y "%ROOT%generate_report.py" "%OUT%\" >nul
copy /Y "%ROOT%requirements.txt" "%OUT%\" >nul
copy /Y "%ROOT%packaging\control_panel.py" "%OUT%\" >nul
copy /Y "%ROOT%packaging\工地照片系統.bat" "%OUT%\" >nul
copy /Y "%ROOT%packaging\config.範本.json" "%OUT%\config.json" >nul
copy /Y "%ROOT%packaging\說明.txt" "%OUT%\" >nul
copy /Y "%ROOT%packaging\README.md" "%OUT%\" >nul
copy /Y "%ROOT%packaging\README_zh.md" "%OUT%\" >nul
copy /Y "%ROOT%packaging\安裝.bat" "%OUT%\" >nul

echo.
echo ====================================================
echo   打包完成！
echo ====================================================
echo.
echo "distribute" 資料夾已經準備好了，裡面是乾淨的安裝包
echo （不含你目前的照片、manifest.csv 等真實工地資料）。
echo.
echo 下一步：把整個 "distribute" 資料夾壓縮成 zip，傳給對方，
echo 對方解壓縮後，雙擊裡面的「安裝.bat」就可以開始安裝。
echo.
pause

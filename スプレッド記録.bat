@echo off
chcp 65001 >nul
cd /d "%~dp0"
title USD/JPY スプレッド記録
echo ============================================
echo   USD/JPY 実測スプレッド記録
echo   松井証券FXの画面の数字をそのまま入力
echo   (やめる場合はこのウィンドウを閉じてください)
echo ============================================
echo.
set /p BID=売値 Bid を入力 (例 157.123):
set /p ASK=買値 Ask を入力 (例 157.125):
set /p EV=重要指標の発表直後ですか? [y/N]:
if /i "%EV%"=="y" (
    python scripts\ops\log_spread.py %BID% %ASK% --event
) else (
    python scripts\ops\log_spread.py %BID% %ASK%
)
echo.
echo 記録しました。ウィンドウを閉じてOKです。
pause

@echo off
chcp 65001 >nul
REM ============================================================
REM  FX研究システム 初回セットアップ(ダブルクリックで実行)
REM  やること: 仮想環境作成 → ライブラリ導入 → データ取得 → 動作確認
REM  所要: 15〜25分(大半はデータダウンロード)。発注機能は一切ありません。
REM ============================================================
cd /d "%~dp0"

echo [1/5] Pythonの確認...
py -3 --version
if errorlevel 1 (
  echo.
  echo   ERROR: Pythonが見つかりません。
  echo   https://www.python.org/downloads/ から Python 3.11以上を
  echo   「Add python.exe to PATH」にチェックを入れてインストール後、再実行してください。
  pause
  exit /b 1
)

echo [2/5] 仮想環境の作成とライブラリ導入(2〜3分)...
if not exist .venv ( py -3 -m venv .venv )
call .venv\Scripts\activate.bat
python -m pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
if errorlevel 1 ( echo ERROR: ライブラリ導入に失敗。この画面を撮ってClaudeに貼ってください & pause & exit /b 1 )

echo [3/5] 価格データの取得(10〜20分。そのまま待つ)...
python scripts\data\download_histdata.py
if errorlevel 1 ( echo ERROR: 価格データ取得に失敗。この画面を撮ってClaudeに貼ってください & pause & exit /b 1 )

echo [4/5] 金利データの取得(数秒)...
python scripts\data\download_dgs10.py

echo [5/5] 動作確認(スモークテスト・発注なし)...
python scripts\live\_smoke.py
if errorlevel 1 ( echo ERROR: 動作確認に失敗。この画面を撮ってClaudeに貼ってください & pause & exit /b 1 )

echo.
echo ============================================================
echo  セットアップ完了!すべて正常です。
echo  日常の使い方は docs\09_user_runbook.md を参照。
echo  このウィンドウは閉じてOKです。
echo ============================================================
pause

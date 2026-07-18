@echo off
chcp 65001 >nul
echo スプレッド記録リマインダー(平日9:30/16:30/22:00)を解除します。
schtasks /Delete /F /TN "FXスプレッド記録_0930"
schtasks /Delete /F /TN "FXスプレッド記録_1630"
schtasks /Delete /F /TN "FXスプレッド記録_2200"
echo 解除しました。再開したい場合はClaude Codeに「リマインダー再登録して」と伝えてください。
pause

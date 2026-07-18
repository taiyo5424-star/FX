# イベント日付の出典と検証記録(2026-07-07)

historical_events.json の全日付は以下の公式ソースで検証済み(収集:リサーチエージェント)。

| カテゴリ | 出典 | 備考 |
|---|---|---|
| FOMC(32件) | federalreserve.gov/monetarypolicy/fomccalendars.htm | 声明14:00 ET。夏18:00/冬19:00 UTC。2025-08-22のnotation voteは除外 |
| 日銀会合(32件) | boj.or.jp/en/mopo/mpmsche_minu/ | 発表時刻不定→engineでワイドウィンドウ(JST昼〜午後) |
| NFP(47件) | bls.gov/schedule/{year}/home.htm | 2025年10月は政府閉鎖で欠落、9月分は11-20遅延発表 |
| CPI(47件) | 同上 + bls.gov/schedule/news_release/cpi.htm | 2025年9月分は10-24特例発表、10月分は公表されず |
| 介入(2024年4日) | mof.go.jp 外国為替平衡操作CSV(日次) | 2023年・2025年・2026Q1はゼロを確認 |
| 介入(2026年4-5月) | mof.go.jp 月次公表 20260529 | 総額11兆7,349億円(月次過去最大)。**日次内訳は2026-08-03〜07公表予定** |

## 要フォローアップ

1. **2026-08-03〜07**: 財務省の2026Q2日次内訳公表後、`intervention` の2026-04-28〜05-27の
   ブランケット除外を実際の介入日に差し替えて再検証する(research/priority_queue.mdに登録済み)
2. 2026年12月以降のBLS日程は未公表 → fetch_calendar.py(週次フィード)でカバー
3. ライブ運用のイベントフィルタは fetch_calendar.py(ForexFactory週次)が主、本ファイルは検証用

# 08. ライブ・シグナルアラートエンジン(PAPER_TRADE〜半自動 execution model B)

`scripts/live/signal_alert_engine.py`。株式デイトレ環境(C:\dev\daytrade の rt_engine)で実運用している
「音アラート＋シグナル記録＋サイズ規律」の運用ノウハウを、本FXプロジェクトの制約に適合させて移植したもの。

## 何をするか / しないか
- **する**: 検証を通った戦略のシグナルを実相場で判定 → 安全ゲート通過なら音アラート＋**発注案(出力形式A)**を提示 → `logs/signals/` に全判定(TRADE/NO_TRADE)を記録。
- **しない**: 発注。松井証券FX規程第9条によりbot発注は禁止(research/matsui_research.md 確定)。本エンジンは提案までで、**実発注はユーザーが注文確認画面と1対1照合して手動実行**(docs/05)。

## パイプライン上の位置(docs/04)
`... → STRESS_TEST → PAPER_TRADE → [承認] → MICRO_LIVE → ...`
本エンジンは **PAPER_TRADE ステージの記録体制**(priority_queue P2-14)。承認前戦略は `approved=False` の
**shadow モード**(音を鳴らさず記録のみ)で、実相場での「シグナルのみ記録・最低20シグナル」を貯める。
APPROVED 後に `approved=True` で alert モード(音＋発注案)に上げる。

## 安全ゲート(すべて config/risk_limits.json と docs/05 準拠)
判定前に必ず `logs/daily/state_YYYY-MM-DD.json` を読む。以下いずれかで **NO_TRADE**(理由を failed_checks に記録):
- 日中状態が読めない(`DAILY_STATE_UNREADABLE`)/ halt_flags あり
- 当日取引数 ≥ max_trades(3)/ 連敗 ≥ 4 / economic_daily_loss ≥ 警戒線(16,000円)
- イベント窓内(data/calendar/no_trade_windows.json)/ スプレッド悪化 / EV_R・保守EV_R が閾値未満

## 使い方
```python
from scripts.live import signal_alert_engine as E
# 1) 検証を通った戦略を LiveStrategy として実装(evaluate は確定バーのみ使用・ルックアヘッド厳禁)
# 2) レート源(ReplaySource か 本番レートアダプタ)を用意
E.run(MyStrategy(), source, poll_sec=1.0)   # approved=False なら自動で shadow
```
スモークテスト: `python scripts/live/_smoke.py`(合成データ・発注なし。正常/日次警戒/状態欠損の3系統を確認)。

## 移植元(daytrade)の知見で本FXに効くもの / 効かないもの
- **効く**: 音アラート＋提案の手動執行モデル(松井は株もFXもbot発注不可で同型)、シグナル全件記録、サイズ規律(リスク額÷SL幅)、承認前は shadow。
- **効かない/FXで作り直し**: エッジ本体(株の平均回帰はFXに転用不可)、コスト構造(呼値→スプレッド/スワップ)、
  セッション(24h・寄り無し)、サイズ依存スリッページ(USD/JPYは深く50万規模では軽微)。
- 既存の検証パイプライン(docs/04)は本プロジェクトが独立に確立済みで、株側と同等以上。**移植すべきは"手法"でなく"運用の器"**。

## TODO(本番レートアダプタ)
`ReplaySource` は検証・スモーク用。本番は松井FXレートの取得方法(公式自動売買の設定値算出に使う読取専用データ、
または許諾されたデータフィード)に合わせて `RateSource` を実装する。認証情報は受け取らない・保持しない(docs/05)。

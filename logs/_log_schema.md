# ログ形式定義

方針:全ログはJSON Lines(1行1レコード)。圧縮・機械集計を優先し、
自由記述は最小限。認証情報・個人情報は記録禁止。

## ディレクトリと命名

```
logs/
├── trades/trade_YYYYMMDD_NNN.json      ← 取引後レビュー(1取引1ファイル)
├── daily/YYYY-MM-DD.json               ← 日次レビュー
├── daily/state_YYYY-MM-DD.json         ← 日中状態(リアルタイム更新)
├── ai_costs/YYYY-MM-DD.jsonl           ← AI利用コスト(1呼び出し1行)
├── signals/YYYY-MM-DD.jsonl            ← シグナル・NO_TRADE判定(1判定1行)
├── spreads/YYYY-MM-DD.jsonl            ← 実測スプレッド観測
└── ops/YYYY-MM-DD.jsonl                ← 操作・照合・エラーログ
```

## 取引後レビュー(trades/)

仕様書第34節の全項目JSON。必須追加フィールド:
`trade_id`(YYYYMMDD_NNN)、`checklist_ref`(発注時チェックリストへの参照)。
勝ってもルール違反なら `rule_followed: false` で失敗として記録。
AIコスト込み赤字は `ai_cost_acceptable: false` で改善対象に分類。

## 日中状態(daily/state_)

```json
{"date":"","equity_jpy":0,"realized_pnl_jpy":0,"unrealized_pnl_jpy":0,
 "execution_costs_jpy":0,"ai_cash_cost_jpy":0,"ai_shadow_cost_jpy":0,
 "economic_daily_loss_jpy":0,"trades_today":0,"consecutive_losses":0,
 "remaining_risk_budget_jpy":0,"halt_flags":[],"last_updated":""}
```
- 全取引判断はこのファイルを読んでから行う。読めなければ NO_TRADE。
- halt_flags 例:"DAILY_WARNING_16000", "STREAK_4", "EVENT_WINDOW", "EXEC_ERROR"

## AIコストログ(ai_costs/)

```json
{"ts":"","task":"","model":"Fable5/cheaper/script","usage_mode":"",
 "in_unc":0,"in_cached":0,"out":0,"cash_jpy":0,"shadow_jpy":0,
 "benefit_type":"","benefit_jpy_est":0,"ratio":0,"cached_reuse":false}
```

## シグナルログ(signals/)

```json
{"ts":"","strategy":"","version":"","signal":"BUY/SELL/NONE",
 "decision":"TRADE/NO_TRADE","failed_checks":[],"net_EV_R":0,
 "conservative_net_EV_R":0,"spread_pips":0,"regime":"","note":""}
```
NO_TRADEも必ず記録(NO_TRADE判断の妥当性を週次で検証するため)。

## スプレッド観測(spreads/)

```json
{"ts":"","bid":0,"ask":0,"spread_pips":0,"session":"","event_window":false}
```
ペーパートレード期間に重点収集し、実測スプレッド分布を構築する。

## 保持・集計

- 生ログは無期限保持(軽量)。週次でサマリーを生成しFable5にはサマリーのみ渡す
  (生ログをそのままFable5に投入しない=トークン削減)。

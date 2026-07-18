# 07. 日次・週次・月次レビュー形式

## 日次レビュー(ルールベース生成、Fable5不使用)

出力先:`logs/daily/YYYY-MM-DD.json`

```json
{
  "date": "", "starting_equity_jpy": "", "ending_equity_jpy": "",
  "daily_realized_pnl_jpy": "", "daily_unrealized_pnl_jpy": "",
  "daily_ai_cash_cost_jpy": "", "daily_ai_shadow_cost_jpy": "",
  "net_daily_pnl_after_ai_cost_jpy": "",
  "max_intraday_drawdown_jpy": "", "economic_daily_loss_jpy": "",
  "daily_loss_limit_jpy": 20000, "daily_warning_line_jpy": 16000,
  "number_of_trades": "", "TRADE_count": "", "NO_TRADE_count": "",
  "rule_violations": "", "browser_or_api_errors": "",
  "max_spread_pips": "", "avg_spread_pips": "", "avg_slippage_pips": "",
  "fable5_calls": "", "cheaper_model_calls": "", "script_or_rule_based_decisions": "",
  "new_candidate_ideas": [],
  "decision_for_next_day": "continue / reduce_risk / pause / paper_trade",
  "ai_cost_decision_for_next_day": "continue / reduce_fable5 / use_cheaper_model / script_only",
  "reason": ""
}
```

日次評価基準:勝敗ではなく (1)ルール遵守 (2)AIコスト込み期待値の維持
(3)NO_TRADE判断の妥当性 (4)損失の分類(正常な損失 vs ルール違反)。
新仮説は最大3件記録、翌日ライブへは反映しない。

## 週次レビュー(Fable5使用可・ユーザー確認必須)

**週次レビュー完了+ユーザー確認まで新規取引停止。**
リスク幅・AI上限の変更はユーザー承認なしに実行しない。

出力:仕様書第13節のUSER_CONFIRMATION_REQUIRED形式JSON(全項目)+以下の要約:
1. 実績EV_R vs 検証時EV_R の乖離(戦略別)
2. AIコスト内訳(cash/shadow別、Fable5/安価モデル/スクリプト比率)
3. 実測スプレッド・スリッページの分布 vs 想定値
4. ルール違反・実行系エラーの一覧と対策
5. 候補戦略の進捗(ステージ移動)
6. recommendation: risk_keep / risk_reduce / risk_pause
7. ai_cost_recommendation: fable5_keep / fable5_reduce / fable5_pause / move_to_cheaper_model

判定原則:
- 週間プラスでも、AIコスト込み期待値・スリッページ・ルール遵守・DDが
  不十分ならリスクを上げない。
- 週間マイナス・AIコスト込みマイナス・ルール違反ありなら、
  リスク縮小またはペーパートレード復帰を提案。

## 月次レビュー(Fable5使用可)

チェック項目:
- 戦略別の期待値劣化(検証時比)/ AIコスト込み期待値の劣化
- レジーム別・時間帯別・指標前後・スプレッド拡大時・低流動性時の損益分解
- 実行系エラー頻度 / Fable5コスト vs Fable5による改善額(回収できているか)
- Fable5を使うべきだった/使うべきでなかった作業の再分類 → config/ai_cost_policy.json更新提案
- 戦略の処遇:継続 / 停止 / 研究継続 / 破棄

月次の目的は取引回数増ではなく、**期待値のない取引と不要なAIコストの削減**。

## 戦略劣化検知(スクリプト常時監視・閾値)

以下1つでも該当 → 該当戦略を自動PAUSED+ユーザー通知:
- 直近20取引:EV_R <= 0 / net_EV_R_after_ai_cost <= 0 / conservative_net_EV_R < 0
- 想定最大連敗数超過 / 実測スリッページ >= 想定×1.5
- 実測スプレッドが想定を継続超過 / AIコストが想定を継続超過
- 最大DDが想定の80%到達 / 指標前後の損失集中 / 同一レジームでの連続損失
- ルール違反1件 / 実行系エラー / 注文・約定不一致
- economic_daily_loss_jpy >= 16,000円(全戦略停止)
再開は原因分析完了+ユーザー承認後のみ。

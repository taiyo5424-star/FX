# 02. 取引前チェックリスト(最終版)

シグナル成立ごとにスクリプトが本チェックリストをJSONで生成する。
**1項目でも FAIL / 不明 / 空欄 → decision = "NO_TRADE"(例外なし)。**
Fable5はこの判定に関与しない(判定不能な異常の原因分析のみ、コストゲート適用)。

## チェック順序(早期NO_TRADEでコスト削減)

コストの安い順に判定し、FAILが出た時点で残りを省略して NO_TRADE を返す:

```
S1. 戦略状態     strategy_status == APPROVED か
S2. 口座状態     ログイン/残高/建玉/注文/損益が全て確認できるか
S3. 日次制限     economic_daily_loss < 16,000 / 取引回数 < 3 / 連敗 < 4
S4. イベント     禁止イベント時間帯でないか(前後30分/重要2時間/介入24時間)
S5. セッション   流動性十分な時間帯か(週明け直後・クローズ前・休場でない)
S6. スプレッド   実測が戦略想定内か、直近平均から異常拡大していないか
S7. レジーム     現在レジームが戦略の検証レジームと一致するか
S8. EV計算       4閾値すべて充足か(docs/03)
S9. サイズ計算   リスク <= min(残高0.5%, 5000円, 日次残り枠)、最悪想定込み
S10. 実行系      ブラウザ/API正常・データフィード正常・二重注文なし
S11. 注文画面照合 事前計算と注文確認画面の全項目一致
```

## 出力JSONスキーマ

```json
{
  "broker": "松井証券",
  "account_equity_jpy": "", "symbol": "USD/JPY",
  "execution_method": "browser / official_api / approved_third_party_tool",
  "strategy_name": "", "strategy_version": "", "strategy_status": "APPROVED",
  "timeframe": "", "session": "Tokyo / London / New_York / Illiquid",
  "market_regime": "", "setup_summary": "",
  "entry_price": "", "stop_loss": "", "take_profit_plan": "",
  "invalidation_condition": "",
  "win_rate_estimate": "", "avg_win_R": "", "avg_loss_R": "",
  "spread_pips": "", "estimated_slippage_pips": "",
  "commission_cost_R": "", "auto_trading_fee_R": "", "swap_impact_R": "",
  "broker_execution_cost_jpy": "",
  "direct_ai_decision_cost_jpy": "", "allocated_research_ai_cost_jpy": "",
  "allocated_monitoring_ai_cost_jpy": "", "total_ai_cost_allocated_jpy": "",
  "total_cost_R": "",
  "EV_R": "", "conservative_EV_R": "", "net_EV_R": "", "conservative_net_EV_R": "",
  "sample_size": "", "backtest_period": "",
  "out_of_sample_result": "", "walk_forward_result": "",
  "current_regime_match": false,
  "daily_realized_pnl_jpy": "", "daily_unrealized_pnl_jpy": "",
  "daily_ai_cash_cost_jpy": "", "daily_ai_shadow_cost_jpy": "",
  "economic_daily_loss_jpy": "", "daily_remaining_risk_budget_jpy": "",
  "risk_per_trade_jpy": "", "max_loss_if_stopped_jpy": "",
  "risk_percent_of_equity": "", "position_size": "",
  "spread_check": "", "liquidity_check": "", "event_risk_check": "",
  "intervention_risk_check": "", "daily_loss_limit_check": "",
  "ai_cost_check": "", "browser_or_api_check": "", "data_feed_check": "",
  "execution_check": "", "order_screen_match_check": "",
  "decision": "TRADE / NO_TRADE", "reason": ""
}
```

## 発注条件(全PASS必須の一覧)

- strategy_status == APPROVED / decision == "TRADE"
- EV_R >= +0.15 / conservative_EV_R >= +0.05 / net_EV_R >= +0.15 / conservative_net_EV_R >= +0.05
- current_regime_match == true
- 全 *_check == PASS(10項目)
- risk_per_trade_jpy <= 5000 かつ daily_remaining_risk_budget_jpy > risk_per_trade_jpy
- stop_loss / take_profit_plan / invalidation_condition が明確

## 発注実行(重要)

全PASS後、**発注案をユーザーへ提示し、ユーザーが発注操作を行う**。
提示フォーマットは最終出力形式A(仕様書第39節)。ユーザー実行後、
注文履歴・建玉照会で意図どおりの反映を確認してから記録する。
不一致・確認不能の場合は即時停止し、自動再送信は行わない。

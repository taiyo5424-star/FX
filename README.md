# USD/JPY 研究進化型・期待値ベース自動売買システム

対象:松井証券FX口座 / USD/JPYのみ / 初期資金 500,000円

## 絶対原則(要約)
1. 検証済み正期待値(AIコスト込み)の取引のみ実行。不明・未検証・条件未達は必ず NO_TRADE。
2. 研究と実運用は完全分離。未承認パターンのライブ使用禁止。
3. 日次最大損失 20,000円(AI cash_cost含む)。警戒ライン 16,000円。
4. 1取引リスク:標準 2,500円(残高0.5%)、絶対上限 5,000円。
5. 1日最大3取引。4連敗で停止。最大DD 6%でペーパートレード降格。
6. 7/8以降、Fable5は重い判断のみ(日次1,000円・週次5,000円以内)。
7. **発注の最終実行は必ずユーザー操作またはユーザーの都度承認を要する。エージェントによる無人発注は行わない。**

## ディレクトリ構成
```
FX自動売買/
├── README.md                    ← 本ファイル(全体アーキテクチャ)
├── config/
│   ├── risk_limits.json         ← リスク上限(変更にはユーザー承認必須)
│   └── ai_cost_policy.json      ← AIコスト管理・モデル委任ルール
├── docs/
│   ├── 01_architecture.md       ← エージェント構造・処理フロー
│   ├── 02_pretrade_checklist.md ← 取引前チェックリスト(最終版)
│   ├── 03_ev_formulas.md        ← 期待値計算式(AIコスト込み・最終版)
│   ├── 04_validation_pipeline.md← 検証パイプライン+過剰最適化防止
│   ├── 05_execution_safety.md   ← ブラウザ/API安全ルール
│   ├── 06_champion_challenger.md← Champion/Challenger運用
│   └── 07_review_templates.md   ← 日次・週次・月次レビュー形式
├── strategies/
│   ├── _library_schema.json     ← 戦略ライブラリのスキーマ
│   ├── candidates/              ← Candidate戦略(IDEA〜PAPER_TRADE)
│   │   └── batch_001_initial_hypotheses.md
│   └── approved/                ← APPROVED戦略(現在:0件)
├── logs/
│   ├── _log_schema.md           ← ログ形式定義
│   ├── trades/                  ← 取引後レビュー(1取引1ファイル)
│   ├── daily/                   ← 日次レビュー
│   └── ai_costs/                ← AI利用コストログ
└── research/
    └── priority_queue.md        ← 研究タスク優先順位表
```

## スクリプト一覧

| スクリプト | 用途 | AI利用 |
|---|---|---|
| scripts/data/download_histdata.py | HistDataからM1データ取得(EST→UTC変換込み) | なし |
| scripts/data/quality_check.py | データ品質検証 → data/quality_report.md | なし |
| scripts/ops/fetch_calendar.py | 経済指標カレンダー取得(毎朝実行)→ 取引禁止ウィンドウ生成 | なし |
| scripts/ops/log_spread.py | 実測スプレッド記録CLI | なし |
| scripts/ops/daily_state.py | 日中状態管理(init/update/trade-result/status) | なし |
| scripts/ops/pretrade_checklist.py | 取引前チェックリスト生成(S1-S11早期NO_TRADE) | なし |
| scripts/backtest/engine.py | 約定シミュレーション・指標計算・イベント除外 | なし |
| scripts/backtest/strategies_batch1.py | C001/C003/C009シグナル生成 | なし |
| scripts/backtest/runner.py | IS/OOS/WF/ストレスの一括検証 | なし |

## 現在の状態(2026-07-08)
- APPROVED戦略:**0件** → ライブ取引は全面 NO_TRADE(これが数値的に正しい状態)
- データ基盤:完成(M1 2023-01〜2026-06、品質検証済み、検証済みイベントフィルタ)
- 検証済み候補:**7件、合格0件**(batch1/batch2レポート+backtest_c010_results.json)
  - REJECTED:C001仲値、C003ロンドンブレイク、C005前日高安反発、C016東京拡大継続、C010金利差乖離
  - RESEARCH_ONLY凍結:C009/C009v2(押し目。OOS参照消費済み、前進検証のみ)
- 重要な教訓:C016で**ルックアヘッドバイアスを偽PASS_ALLの段階で検出・修正**
  (docs/04「既知のルックアヘッド落とし穴」「多重検定への警戒」に恒久記録)
- C015研究:東京レンジ拡大→トレンド日確率2.49倍(統計は有効、EV変換は未達成)
- 松井証券:bot発注は規程違反と確定(research/matsui_research.md)→ 発注は必ずユーザー操作
- 次のアクション:実測スプレッド収集(M2)、8月上旬の介入日次内訳反映(M3)、
  月次レビュー時に新仮説バッチ生成(research/priority_queue.md)
- 要ユーザー対応:config/risk_limits.json 初期値承認、実測スプレッド収集協力

## 運用フロー(1日の流れ、7/8以降)
1. **朝(スクリプト/ルールベース)**:経済指標カレンダー確認 → イベント日ならその時間帯を取引禁止登録
2. **セッション中(スクリプト/ルールベース)**:APPROVED戦略のシグナル条件を機械判定。Fable5は呼ばない。
3. **シグナル成立時**:取引前チェックリスト(docs/02)を機械生成 → 全PASSなら**ユーザーへ発注案を提示** → ユーザー実行
4. **取引後(スクリプト)**:取引後レビュー記録(logs/trades/)
5. **日次終了(ルールベース、Fable5不使用)**:日次レビュー記録
6. **週次(Fable5可)**:週次レビュー+ユーザー確認。リスク幅・AI上限の変更はユーザー承認必須。

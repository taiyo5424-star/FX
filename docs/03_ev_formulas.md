# 03. 期待値計算式(最終版・AIコスト込み)

## 1. 取引期待値(円)

```
gross_trade_EV_jpy = 勝率 × 平均利益円 − 敗率 × 平均損失円

broker_execution_cost_jpy = スプレッド + スリッページ + 手数料
                          + 自動売買手数料 + スワップ影響 + その他取引コスト

net_EV_jpy = gross_trade_EV_jpy
           − broker_execution_cost_jpy
           − direct_ai_decision_cost_jpy
           − allocated_research_ai_cost_jpy
           − allocated_monitoring_ai_cost_jpy

net_EV_R = net_EV_jpy ÷ risk_per_trade_jpy
```

## 2. AIコスト配賦

```
allocated_research_ai_cost_jpy =
    戦略の累積研究AIコスト ÷ 今後期待される有効取引回数
    (有効取引回数は保守的に見積もる。根拠のない大きな分母を使わない)

allocated_monitoring_ai_cost_jpy =
    当日の監視・レビューAIコスト ÷ 当日の有効取引回数
    (取引0回の日は日次コストとして記録。翌日以降へ繰り越さない)
```

## 3. 保守的期待値(conservative)

各入力を以下のとおり悪化させて再計算する:

| 入力 | 保守化ルール(初期値) |
|---|---|
| 勝率 | 検証値 − max(5%pt, 検証標準誤差×1.5) |
| 平均利益 | 検証値 × 0.85 |
| 平均損失 | 検証値 × 1.15 |
| スプレッド | 実測平均 × 1.5 |
| スリッページ | 想定 × 2.0 |
| AIコスト | 見積 × 1.5(usage_mode=unknownなら × 3.0) |

## 4. 取引許可の最低条件(すべて必須)

```
EV_R                  >= +0.15
conservative_EV_R     >= +0.05
net_EV_R              >= +0.15
conservative_net_EV_R >= +0.05
```
- AIコスト算入前にプラスでも、算入後に不足すれば NO_TRADE。
- AIコスト不明時は保守的に高く見積もる(正当化に使わない)。

## 5. 戦略タイプ別の利幅下限

| タイプ | 条件 |
|---|---|
| スキャルピング | 平均利益 >= 3 ×(スプレッド+スリッページ+AIコスト配賦) ※ただしFable5毎取引呼び出し禁止のため実質スクリプト運用限定 |
| デイトレード | 平均利益 >= 5 ×(総取引コスト+AIコスト配賦) |
| スイング | スワップ・週末ギャップ・AIコスト配賦込みで正のnet_EV |

## 6. AI呼び出しコスト(参考式)

```
ai_call_cost_usd = uncached_in/1M×10 + cached_in/1M×10×0.10 + out/1M×50
ai_call_cost_jpy = ai_call_cost_usd × USD/JPYレート
```
- subscription_included → cash_cost=0、shadow_costとして同額を記録
- usage_credit / api → cash_costとして期待値から控除
- unknown → 保守的に高く見積もる

## 7. 数値例(サニティチェック用)

デイトレ想定:勝率45%、平均利益6,000円、平均損失2,500円、リスク2,500円
```
gross = 0.45×6000 − 0.55×2500 = 2700 − 1375 = +1325円
実行コスト(スプレッド0.2pips+スリッページ0.3pips、1万通貨) ≈ 50円
AI配賦(研究3万円÷100回=300円、監視100円/回) = 400円
net_EV = 1325 − 50 − 0 − 300 − 100 = +875円 → net_EV_R = +0.35 ✔
```
→ この規模感なら成立余地あり。逆に平均利益が数百円のスキャルは
AI配賦を入れると容易に消えることが式から直ちに分かる。

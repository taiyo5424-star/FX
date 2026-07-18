# -*- coding: utf-8 -*-
"""データ品質検証(docs/04準拠)
チェック項目:
  1. OHLC整合性(high>=max(o,c), low<=min(o,c))
  2. 価格の妥当レンジ(USD/JPY 2023-2026: 100〜170円)
  3. 重複タイムスタンプ
  4. 週末データの混入(金曜NYクローズ〜日曜NYオープン)
  5. 日別バー数の分布(欠損検出。HistDataはティックなし分を省略する仕様に留意)
  6. 異常ジャンプ(連続バー間 > 100pips、週明けギャップを除く)
出力: data/quality_report.md
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
df = pd.read_parquet(ROOT / "data" / "usdjpy_m1.parquet")

lines = ["# USD/JPY M1 データ品質レポート", "",
         f"- 行数: {len(df):,}",
         f"- 期間(UTC): {df['time_utc'].iloc[0]} 〜 {df['time_utc'].iloc[-1]}", ""]

# 1. OHLC整合性
bad_ohlc = df[(df["high"] < df[["open", "close"]].max(axis=1) - 1e-9) |
              (df["low"] > df[["open", "close"]].min(axis=1) + 1e-9)]
lines.append(f"## 1. OHLC整合性違反: {len(bad_ohlc)}件")

# 2. 価格レンジ
out_range = df[(df["low"] < 100) | (df["high"] > 170)]
lines.append(f"## 2. 妥当レンジ(100-170)外: {len(out_range)}件")
lines.append(f"- 実レンジ: {df['low'].min():.3f} 〜 {df['high'].max():.3f}")

# 3. 重複
dup = df["time_utc"].duplicated().sum()
lines.append(f"## 3. 重複タイムスタンプ: {dup}件")

# 4. 週末混入(UTC: 金曜22:00以降〜日曜21:00以前を「週末」とみなす)
t = df["time_utc"].dt
wd, hr = t.weekday, t.hour
weekend = df[((wd == 4) & (hr >= 22)) | (wd == 5) | ((wd == 6) & (hr < 21))]
lines.append(f"## 4. 週末時間帯のバー: {len(weekend)}件(NYクローズ22:00UTC想定・夏冬で±1h誤差あり)")

# 5. 日別バー数
df["date"] = t.date
daily = df.groupby("date").size()
busdays = daily[daily.index.map(lambda d: d.weekday() < 5)]
lines.append("## 5. 日別バー数(平日)")
lines.append(f"- 平日日数: {len(busdays)}、中央値: {busdays.median():.0f} 本/日(理論最大1440)")
lines.append(f"- 1000本未満の平日: {(busdays < 1000).sum()}日(休日・年末年始を含む)")
low_days = busdays[busdays < 1000].sort_values()
lines.append(f"- 最少10日: {[(str(d), int(v)) for d, v in low_days.head(10).items()]}")

# 6. 異常ジャンプ
df["prev_close"] = df["close"].shift(1)
df["gap_pips"] = (df["open"] - df["prev_close"]).abs() * 100
df["dt_min"] = df["time_utc"].diff().dt.total_seconds() / 60
jumps = df[(df["gap_pips"] > 100) & (df["dt_min"] <= 10)]
lines.append(f"## 6. 異常ジャンプ(10分以内に100pips超): {len(jumps)}件")
for _, r in jumps.head(15).iterrows():
    lines.append(f"- {r['time_utc']} gap={r['gap_pips']:.0f}pips ({r['prev_close']:.3f}→{r['open']:.3f})")

# 7. 大きな時間ギャップ(平日活発時間帯で60分超の欠損)
active = df[(df["dt_min"] > 60) & (df["dt_min"] < 2500)]
act = active[~(((active["time_utc"].dt.weekday == 4) & (active["time_utc"].dt.hour >= 21)) |
               (active["time_utc"].dt.weekday >= 5) |
               ((active["time_utc"].dt.weekday == 0) & (active["time_utc"].dt.hour < 1)))]
lines.append(f"## 7. 平日60分超の連続欠損: {len(act)}件(週明け除く)")
for _, r in act.head(15).iterrows():
    lines.append(f"- {r['time_utc']} 直前から{r['dt_min']:.0f}分欠損")

lines.append("")
lines.append("## 既知の制約")
lines.append("- HistDataはBIDベース。スプレッド情報なし → コストは保守値(0.4pips〜)を別途適用")
lines.append("- ティックのない分は行が存在しない(欠損=市場静穏の可能性)")
lines.append("- 出来高情報なし")
lines.append("- 松井証券の実レート・実スプレッドとは乖離がありうる(PAPER_TRADEで実測比較必須)")

report = "\n".join(str(x) for x in lines)
(ROOT / "data" / "quality_report.md").write_text(report, encoding="utf-8")
print(report)

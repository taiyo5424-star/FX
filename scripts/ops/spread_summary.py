# -*- coding: utf-8 -*-
"""実測スプレッドの自動集計(logs/spreads/*.jsonl → research/spread_summary.md)
実行: python scripts/ops/spread_summary.py(引数不要・何度でも実行可)"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
files = sorted((ROOT / "logs" / "spreads").glob("*.jsonl"))
rows = []
for f in files:
    for line in f.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
if not rows:
    print("記録がまだありません(logs/spreads/ が空)")
    raise SystemExit(0)

df = pd.DataFrame(rows)
df["ts"] = pd.to_datetime(df["ts"])
lines = ["# 実測スプレッド集計", "",
         f"- 記録数: {len(df)}({df['ts'].min():%Y-%m-%d} 〜 {df['ts'].max():%Y-%m-%d}、{df['ts'].dt.date.nunique()}日分)",
         f"- 全体: 中央値 {df['spread_pips'].median():.2f}pips / 平均 {df['spread_pips'].mean():.2f} / 最大 {df['spread_pips'].max():.2f}",
         "", "| セッション | n | 中央値 | 平均 | 最大 |", "|---|---|---|---|---|"]
for s, g in df.groupby("session"):
    lines.append(f"| {s} | {len(g)} | {g['spread_pips'].median():.2f} | {g['spread_pips'].mean():.2f} | {g['spread_pips'].max():.2f} |")
ev = df[df["event_window"]]
if len(ev):
    lines.append(f"| イベント直後 | {len(ev)} | {ev['spread_pips'].median():.2f} | {ev['spread_pips'].mean():.2f} | {ev['spread_pips'].max():.2f} |")
lines += ["", "## バックテスト仮定との比較",
          f"- 検証で使用した保守値: 0.4pips → 実測中央値: {df['spread_pips'].median():.2f}pips",
          "- 実測が0.3pips超で常態化する場合、既存検証のコスト仮定を上方修正して再実行が必要",
          f"- ペーパートレード開始の目安(2週間 or 20記録以上): {'達成' if df['ts'].dt.date.nunique() >= 14 or len(df) >= 20 else '未達'}"]
out = ROOT / "research" / "spread_summary.md"
out.write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))

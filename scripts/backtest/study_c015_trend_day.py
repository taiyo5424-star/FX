# -*- coding: utf-8 -*-
"""C015研究: トレンド日の早期判定は可能か(IS期間のみ: 2023-01〜2025-06)
定義:
  トレンド日 = 日足レンジ >= 1.3×ATR14 かつ 終値がレンジ端20%以内(方向を持って引けた日)
早期特徴量(すべて当日15:00 JSTまでに確定する情報のみ):
  F1: 東京時間(9-15時)のレンジが直近20日東京レンジ平均の何倍か
  F2: 15:00時点の価格が東京レンジのどの位置か(端=方向性)
  F3: 9:00-11:00の値幅方向と15:00までの方向の一致
  F4: 前日がトレンド日だったか
出力: research/study_c015_trend_day.md(条件付き確率表)
"""
from pathlib import Path

import numpy as np
import pandas as pd

from engine import PIP, load_data
from strategies_batch1 import JST_9H, JST_15H, build_daily

ROOT = Path(__file__).resolve().parents[2]
IS_END = pd.Timestamp("2025-07-01", tz="UTC")

df = load_data()
df = df[df["time_utc"] < IS_END].reset_index(drop=True)  # IS期間のみ
daily = build_daily(df)
jm = df["jst_min"].values

# 日足側: トレンド日ラベル
d = daily.dropna(subset=["atr14"]).reset_index(names="day")
rng = d["high"] - d["low"]
pos_in_range = (d["close"] - d["low"]) / rng.replace(0, np.nan)
d["trend_day"] = (rng >= 1.3 * d["atr14"]) & ((pos_in_range >= 0.8) | (pos_in_range <= 0.2))

# 分足側: 東京時間の特徴量(JST日付ベース)
g = df.groupby("jst_date")
feats = []
for day, idx in g.indices.items():
    if day.weekday() >= 5:
        continue
    seg = np.asarray(idx)
    tokyo = seg[(jm[seg] >= JST_9H) & (jm[seg] < JST_15H)]
    if len(tokyo) < 200:
        continue
    early = seg[(jm[seg] >= JST_9H) & (jm[seg] < 660)]   # 9:00-11:00
    if len(early) < 60:
        continue
    t_hi = df["high"].values[tokyo].max()
    t_lo = df["low"].values[tokyo].min()
    t_open = df["open"].values[tokyo[0]]
    t_close = df["close"].values[tokyo[-1]]
    e_dir = np.sign(df["close"].values[early[-1]] - df["open"].values[early[0]])
    t_dir = np.sign(t_close - t_open)
    feats.append(dict(day=day, tokyo_range_pips=(t_hi - t_lo) / PIP,
                      close_pos=(t_close - t_lo) / max(t_hi - t_lo, 1e-9),
                      dir_consistent=(e_dir == t_dir) and e_dir != 0))
f = pd.DataFrame(feats)
f["tokyo_range_ratio"] = f["tokyo_range_pips"] / f["tokyo_range_pips"].rolling(20).mean()

# トレンド日ラベルと結合(JST日付≒NY日付のずれ: JST日dの東京時間はNY日dに属する)
lab = {str(r["day"]): bool(r["trend_day"]) for _, r in d.iterrows()}
prev_lab = {str(d.iloc[i]["day"]): bool(d.iloc[i - 1]["trend_day"]) for i in range(1, len(d))}
f["trend_day"] = f["day"].map(lambda x: lab.get(str(x)))
f["prev_trend"] = f["day"].map(lambda x: prev_lab.get(str(x)))
f = f.dropna(subset=["trend_day", "tokyo_range_ratio"])
f["trend_day"] = f["trend_day"].astype(bool)

base = f["trend_day"].mean()
lines = ["# C015研究: トレンド日の早期判定(IS期間のみ)", "",
         f"- 対象日数: {len(f)}, トレンド日基礎確率: {base:.1%}", "",
         "| 条件(15:00 JSTまでに判定可能) | 日数 | P(トレンド日) | リフト |",
         "|---|---|---|---|"]

conds = {
    "東京レンジ比>=1.3": f["tokyo_range_ratio"] >= 1.3,
    "東京レンジ比<=0.7(小動き)": f["tokyo_range_ratio"] <= 0.7,
    "15時終値がレンジ端20%": (f["close_pos"] >= 0.8) | (f["close_pos"] <= 0.2),
    "9-11時方向と15時方向一致": f["dir_consistent"],
    "端20% かつ 方向一致": ((f["close_pos"] >= 0.8) | (f["close_pos"] <= 0.2)) & f["dir_consistent"],
    "端20% かつ レンジ比>=1.2": ((f["close_pos"] >= 0.8) | (f["close_pos"] <= 0.2)) & (f["tokyo_range_ratio"] >= 1.2),
    "前日がトレンド日": f["prev_trend"] == True,
}
for name, c in conds.items():
    sub = f[c]
    if len(sub) >= 30:
        p = sub["trend_day"].mean()
        lines.append(f"| {name} | {len(sub)} | {p:.1%} | {p / base:.2f}x |")
    else:
        lines.append(f"| {name} | {len(sub)} | (n<30) | - |")

lines += ["", "## 解釈メモ",
          "- リフト1.5x以上の条件はC009v2/C003系の日中ゲート素材として有望",
          "- 本研究はIS期間のみ。採用時は候補戦略の検証パイプラインを通すこと",
          "- 「トレンド日」ラベルはNYクローズ日足、特徴量はJST東京時間(同一営業日)"]
(ROOT / "research" / "study_c015_trend_day.md").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))

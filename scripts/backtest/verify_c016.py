# -*- coding: utf-8 -*-
"""C016のSkeptic検証: 取引明細を生データと独立に突合"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from engine import PIP, load_data, eu_dst

ROOT = Path(__file__).resolve().parents[2]
tr = pd.read_csv(ROOT / "research" / "trades_C016.csv", parse_dates=["entry_time", "exit_time"])
df = load_data()

print("=== 基本統計 ===")
print(f"n={len(tr)}, long={int((tr['dir'] == 1).sum())}, short={int((tr['dir'] == -1).sum())}")
for d_ in (1, -1):
    sub = tr[tr["dir"] == d_]
    print(f"  dir={d_:+d}: n={len(sub)}, EV_R={sub['R'].mean():.3f}, win={float((sub['R'] > 0).mean()):.2%}")
print("year別 dir内訳:")
tr["year"] = tr["entry_time"].dt.year
print(tr.groupby(["year", "dir"])["R"].agg(["count", "mean"]).round(3))

print("\n=== 上位10取引(利益) ===")
for _, r in tr.nlargest(10, "R").iterrows():
    print(f"  {r['entry_time']} dir={r['dir']:+d} entry={r['entry']:.3f} exit={r['exit']:.3f} "
          f"sl={r['sl_pips']:.0f}p R={r['R']:.2f} reason={r['reason']}")

print("\n=== exit理由内訳 ===")
print(tr.groupby("reason")["R"].agg(["count", "mean"]).round(3))

# 手動再計算(3件サンプル: 最大勝ち、中央、最大負け)
print("\n=== 生データ突合(3件) ===")
samples = pd.concat([tr.nlargest(1, "R"), tr.iloc[[len(tr) // 2]], tr.nsmallest(1, "R")])
jm = df["jst_min"].values
um = df["utc_min"].values
for _, r in samples.iterrows():
    et = pd.Timestamp(r["entry_time"])
    jst_date = (et + pd.Timedelta(hours=9)).date()
    day_bars = df[df["jst_date"] == jst_date]
    tokyo = day_bars[(day_bars["jst_min"] >= 540) & (day_bars["jst_min"] < 900)]
    t_hi, t_lo = tokyo["high"].max(), tokyo["low"].min()
    rng = (t_hi - t_lo) / PIP
    t_dir = 1 if tokyo["close"].iloc[-1] > tokyo["open"].iloc[0] else -1
    ws = (7 if eu_dst(jst_date) else 8) * 60
    lon_bars = day_bars[day_bars["utc_min"] >= ws]
    manual_entry = lon_bars["open"].iloc[0] if len(lon_bars) else np.nan
    print(f"  {jst_date}: tokyo_rng={rng:.1f}p 方向={t_dir:+d}(記録{r['dir']:+d}) "
        f"手動entry={manual_entry:.3f}(記録{r['entry']:.3f}) 一致={abs(manual_entry - r['entry']) < 1e-6}")

# 過去20日平均との比(独立再計算)
print("\n=== ratio独立再計算(最大勝ちの日) ===")
big = tr.nlargest(1, "R").iloc[0]
jd = (pd.Timestamp(big["entry_time"]) + pd.Timedelta(hours=9)).date()
all_days = sorted(df["jst_date"].unique())
hist = []
for d_ in all_days:
    if d_ > jd:
        break
    bars = df[df["jst_date"] == d_]
    tk = bars[(bars["jst_min"] >= 540) & (bars["jst_min"] < 900)]
    if len(tk) < 200:
        continue
    r_ = (tk["high"].max() - tk["low"].min()) / PIP
    if d_ == jd:
        print(f"  当日レンジ={r_:.1f}p, 過去20日平均={np.mean(hist[-20:]):.1f}p, ratio={r_ / np.mean(hist[-20:]):.2f}")
        break
    hist.append(r_)

# 夜間イベント(NFP/CPI/FOMC当日)への依存度
ev = json.loads((ROOT / "data" / "calendar" / "historical_events.json").read_text(encoding="utf-8"))
event_days = set(ev["nfp"]) | set(ev["cpi"]) | set(ev["fomc"])
tr["jst_date"] = (tr["entry_time"] + pd.Timedelta(hours=9)).dt.date.astype(str)
tr["utc_date"] = tr["entry_time"].dt.date.astype(str)
on_ev = tr[tr["utc_date"].isin(event_days)]
off_ev = tr[~tr["utc_date"].isin(event_days)]
print(f"\n=== 夜間イベント日依存({len(on_ev)}/{len(tr)}件がNFP/CPI/FOMC当日) ===")
print(f"  イベント日: EV_R={on_ev['R'].mean():.3f} total={on_ev['R'].sum():.1f}")
print(f"  非イベント日: EV_R={off_ev['R'].mean():.3f} total={off_ev['R'].sum():.1f} n={len(off_ev)}")
is_off = off_ev[off_ev["entry_time"] < pd.Timestamp("2025-07-01", tz="UTC")]
print(f"  非イベント日のIS: n={len(is_off)}, EV_R={is_off['R'].mean():.3f}")

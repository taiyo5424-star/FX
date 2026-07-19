# -*- coding: utf-8 -*-
"""C017検証ランナー(解禁ゲート付き)

事前登録(2026-07-18確定・変更禁止):
- IS = 〜2026-06-30(旧OOSは7回参照済みのため全てISに編入。真のOOSは新データのみ)
- OOS = 2026-07-01以降の新データ(C010検証時に存在しなかった期間)
- 解禁条件: 実行日が2027-01-05以降 かつ 価格データが2026-12-31以降まで存在
- グリッド(16通り≤50): z_thr∈{1.5,2.0} × sl_atr∈{1.0,1.4} × tp_atr∈{1.5,2.5}
  × timeout_days∈{2,4}。min_corr=0.3固定。選択はIS成績のプラトーのみ。
- 合格基準: 既存checks + OOS(新データ)EV_R 95%CI下限>0 + OOS n>=25
  (低頻度のためOOS期間6ヶ月では n が不足する場合、判定を保留し翌四半期まで延長)

実行前提: data/usdjpy_m1.parquet が2026-12-31以降まで更新済みであること
(scripts/data/download_histdata.py のMONTHS_2026を拡張して再取得する)。
"""
import datetime as dt
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from engine import (CostModel, STRESS, conservative_EV_R, load_data,
                    load_event_windows, make_event_mask, metrics, simulate)
from runner import plateau_pick
from strategies_c010 import build_joint_daily
from strategies_c017 import c017_entries

ROOT = Path(__file__).resolve().parents[2]
UNLOCK_DATE = dt.date(2027, 1, 5)
IS_END = pd.Timestamp("2026-07-01", tz="UTC")   # ここより後が真のOOS(新データ)
REQUIRED_DATA_END = pd.Timestamp("2026-12-31", tz="UTC")

GRID = [dict(z_thr=z, sl_atr=sa, tp_atr=ta, timeout_days=td)
        for z, sa, ta, td in itertools.product([1.5, 2.0], [1.0, 1.4], [1.5, 2.5], [2, 4])]

# ---------- 解禁ゲート ----------
today = dt.date.today()
if today < UNLOCK_DATE:
    sys.exit(f"LOCKED: C017の検証解禁は{UNLOCK_DATE}以降(現在{today})。"
             "同一データ再検証の禁止(docs/04)により実行を拒否します。")
df = load_data()
data_end = df["time_utc"].iloc[-1]
if data_end < REQUIRED_DATA_END:
    sys.exit(f"LOCKED: 価格データが{data_end}まで。{REQUIRED_DATA_END}以降まで更新後に実行"
             "(download_histdata.pyのMONTHS_2026/2027を拡張)。")

mask = make_event_mask(df, load_event_windows())
joint = build_joint_daily(df)
cost = CostModel()
results = []
for p in GRID:
    tr = simulate(df, c017_entries(df, mask, joint=joint, **p), cost)
    if len(tr) == 0:
        continue
    results.append(dict(params=p, trades=tr,
                        is_m=metrics(tr[tr["entry_time"] < IS_END]),
                        oos_m=metrics(tr[tr["entry_time"] >= IS_END])))

chosen = plateau_pick(results)
is_m, oos_m = chosen["is_m"], chosen["oos_m"]
cons_is = conservative_EV_R(is_m)
oos_r = chosen["trades"][chosen["trades"]["entry_time"] >= IS_END]["R"].values
ci_lo = (float(oos_r.mean() - 1.96 * oos_r.std(ddof=1) / np.sqrt(len(oos_r)))
         if len(oos_r) >= 2 else -9.0)
stress_m = metrics(simulate(df, c017_entries(df, mask, joint=joint, **chosen["params"]),
                            CostModel(**STRESS)))

checks = {
    "IS_EV_R>=0.15": is_m.get("EV_R", -9) >= 0.15,
    "IS_conservative>=0.05": (cons_is or -9) >= 0.05,
    "IS_PF>=1.3": is_m.get("PF", 0) >= 1.3,
    "top5_share<0.5": (is_m.get("top5_profit_share") or 1) < 0.5,
    "OOS_n>=25": oos_m.get("n", 0) >= 25,
    "OOS_EV_R>0": oos_m.get("EV_R", -9) > 0,
    "OOS_95CI_lower>0": ci_lo > 0,
    "STRESS_EV_R>=0": stress_m.get("EV_R", -9) >= 0,
}
if not checks["OOS_n>=25"]:
    verdict = "DEFER(OOSサンプル不足。翌四半期まで判定延長)"
elif all(checks.values()):
    verdict = "PASS_ALL"
else:
    verdict = "FAIL"

out = {"C017": dict(chosen_params=chosen["params"],
                    IS=is_m, IS_conservative_EV_R=round(cons_is, 3) if cons_is == cons_is else None,
                    OOS_newdata=oos_m, OOS_95CI_lower=round(ci_lo, 3),
                    stress=stress_m, checks=checks, verdict=verdict,
                    data_end=str(data_end), run_date=str(today))}


def default(x):
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.floating):
        return float(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return str(x)


(ROOT / "research" / "backtest_c017_results.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1, default=default), encoding="utf-8")
chosen["trades"].to_csv(ROOT / "research" / "trades_C017.csv", index=False)
print(f"C017: IS n={is_m.get('n')} EV={is_m.get('EV_R', 0):.3f} "
      f"OOS n={oos_m.get('n')} EV={oos_m.get('EV_R', 0):.3f} CI_lo={ci_lo:.3f} -> {verdict}")
print("entry UTC時刻分布(時):", sorted(chosen["trades"]["entry_time"].dt.hour.unique()))

# -*- coding: utf-8 -*-
"""C010検証(パイプライン・閾値は既存と同一)"""
import itertools
import json
from pathlib import Path

import numpy as np

from engine import (CostModel, STRESS, conservative_EV_R, load_data,
                    load_event_windows, make_event_mask, metrics, simulate)
from runner import IS_END, plateau_pick, wf_windows
from strategies_c010 import build_joint_daily, c010_entries

ROOT = Path(__file__).resolve().parents[2]
GRID = [dict(z_thr=z, sl_atr=sa, tp_atr=ta, timeout_days=td)
        for z, sa, ta, td in itertools.product([1.5, 2.0], [1.0, 1.4], [1.0, 1.5], [2, 4])]

df = load_data()
mask = make_event_mask(df, load_event_windows())
joint = build_joint_daily(df)
print(f"joint daily rows={len(joint)}, corr60中央値={joint['corr60'].median():.2f}")
cost = CostModel()
results = []
for p in GRID:
    tr = simulate(df, c010_entries(df, mask, joint=joint, **p), cost)
    if len(tr) == 0:
        continue
    results.append(dict(params=p, trades=tr,
                        is_m=metrics(tr[tr["entry_time"] < IS_END]),
                        oos_m=metrics(tr[tr["entry_time"] >= IS_END])))

chosen = plateau_pick(results)
is_m, oos_m = chosen["is_m"], chosen["oos_m"]
cons_is = conservative_EV_R(is_m)
evs = [r["is_m"]["EV_R"] for r in results]

wf = []
for tr_s, tr_e, te_e in wf_windows():
    cands = []
    for r in results:
        sub = r["trades"][(r["trades"]["entry_time"] >= tr_s) & (r["trades"]["entry_time"] < tr_e)]
        if len(sub) >= 8:
            cands.append(dict(params=r["params"], trades=r["trades"], is_m=metrics(sub)))
    if not cands:
        continue
    pick = plateau_pick(cands)
    test = pick["trades"][(pick["trades"]["entry_time"] >= tr_e) & (pick["trades"]["entry_time"] < te_e)]
    m = metrics(test)
    if m.get("n", 0) > 0:
        wf.append(dict(train=str(tr_s.date()), test_end=str(te_e.date()),
                       n=m["n"], EV_R=round(m["EV_R"], 3), total_R=round(m["total_R"], 1)))
wf_pos = sum(1 for w in wf if w["EV_R"] > 0)
wf_total = sum(w["total_R"] for w in wf)
stress_m = metrics(simulate(df, c010_entries(df, mask, joint=joint, **chosen["params"]),
                            CostModel(**STRESS)))

checks = {
    "sample_size(IS)>=60": is_m.get("n", 0) >= 60,
    "IS_EV_R>=0.15": is_m.get("EV_R", -9) >= 0.15,
    "IS_conservative>=0.05": (cons_is or -9) >= 0.05,
    "IS_PF>=1.3": is_m.get("PF", 0) >= 1.3,
    "top5_share<0.5": (is_m.get("top5_profit_share") or 1) < 0.5,
    "OOS_EV_R>0": oos_m.get("EV_R", -9) > 0,
    "OOS_degradation<50%": (oos_m.get("EV_R", -9) >= 0.5 * is_m.get("EV_R", 9)
                            if is_m.get("EV_R", 0) > 0 else False),
    "WF>=4windows": len(wf) >= 4,
    "WF_75%_positive": wf_pos >= 0.75 * len(wf) if wf else False,
    "WF_total_R>0": wf_total > 0,
    "STRESS_EV_R>=0": stress_m.get("EV_R", -9) >= 0,
}
verdict = "PASS_ALL" if all(checks.values()) else "FAIL"


def default(x):
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.floating):
        return float(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return str(x)


out = {"C010": dict(chosen_params=chosen["params"],
                    grid_stats=dict(n_configs=len(results),
                                    pct_positive=float(np.mean([e > 0 for e in evs])),
                                    ev_min=round(min(evs), 3), ev_max=round(max(evs), 3),
                                    ev_median=round(float(np.median(evs)), 3)),
                    IS=is_m, IS_conservative_EV_R=round(cons_is, 3) if cons_is == cons_is else None,
                    OOS=oos_m, walk_forward=wf,
                    wf_positive_windows=f"{wf_pos}/{len(wf)}", wf_total_R=round(wf_total, 1),
                    stress=stress_m, checks=checks, verdict=verdict)}
(ROOT / "research" / "backtest_c010_results.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1, default=default), encoding="utf-8")
chosen["trades"].to_csv(ROOT / "research" / "trades_C010.csv", index=False)
print(f"C010: IS n={is_m.get('n')} EV_R={is_m.get('EV_R', 0):.3f} cons={cons_is:.3f} "
      f"OOS n={oos_m.get('n')} EV_R={oos_m.get('EV_R', 0):.3f} "
      f"WF {wf_pos}/{len(wf)} total={wf_total:.1f} stress={stress_m.get('EV_R', 0):.3f} -> {verdict}")
print("grid:", out["C010"]["grid_stats"])
# Skeptic用: エントリー時刻分布チェック(ルックアヘッド検査)
et = chosen["trades"]["entry_time"]
print("entry UTC時刻の分布(時):", sorted(et.dt.hour.unique()))

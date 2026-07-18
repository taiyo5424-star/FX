# -*- coding: utf-8 -*-
"""第3陣検証(C018/C019)。パイプライン・閾値は既存runnerと同一+OOS95%CI要求。
事前登録: strategies/candidates/batch_003_prereg.md
"""
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

from engine import (CostModel, STRESS, conservative_EV_R, load_data,
                    load_event_windows, make_event_mask, metrics, simulate)
from runner import IS_END, plateau_pick, wf_windows
from strategies_batch1 import build_daily
from strategies_batch3 import apply_swap, c018_entries, c019_entries

ROOT = Path(__file__).resolve().parents[2]

GRIDS = {
    "C018": [dict(k_min=k, thr_pips=th, sl_pips=sl, hold_hours=hh, tp_mult=tp)
             for k, th, sl, hh, tp in itertools.product(
                 [15, 30], [10.0, 15.0], [12.0, 18.0], [4, 8], [None, 1.5])],
    "C019": [dict(lookback=lb, sl_atr=sa, hold_days=hd, strength_f=f)
             for lb, sa, hd, f in itertools.product(
                 [10, 20, 40], [1.5, 2.5], [3, 5], [0.0, 0.5])],
}
MIN_N = {"C018": 60, "C019": 60}  # 低頻度枠(3年+データ)

df = load_data()
events = json.loads((ROOT / "data" / "calendar" / "historical_events.json").read_text(encoding="utf-8"))
all_mask = make_event_mask(df, load_event_windows())
# 介入ウィンドウのみのマスク(C018のエントリー禁止用)
iv_windows = [(pd.Timestamp(f"{d} 00:00", tz="UTC"),
               pd.Timestamp(f"{d} 00:00", tz="UTC") + pd.Timedelta(hours=48))
              for d in events.get("intervention", [])]
iv_mask = make_event_mask(df, iv_windows)
daily = build_daily(df)
cost = CostModel()


def gen(name, params, cost_model, intervention_excl=True):
    if name == "C018":
        tr = simulate(df, c018_entries(df, events,
                                       intervention_mask=iv_mask if intervention_excl else None,
                                       **params), cost_model)
        return tr
    tr = simulate(df, c019_entries(df, all_mask, daily=daily, **params), cost_model)
    if cost_model.spread_pips >= 0.8:   # ストレス時: 受取0・支払い×1.5
        return apply_swap(tr, long_pips_per_day=0.0, short_pips_per_day=-3.0)
    return apply_swap(tr)


def oos_ci_lower(trades):
    oos = trades[trades["entry_time"] >= IS_END]["R"].values
    if len(oos) < 2:
        return -9.0
    return float(oos.mean() - 1.96 * oos.std(ddof=1) / np.sqrt(len(oos)))


out = {}
for name, grid in GRIDS.items():
    print(f"\n=== {name}: grid={len(grid)} ===", flush=True)
    results = []
    for p in grid:
        tr = gen(name, p, cost)
        if len(tr) == 0:
            continue
        results.append(dict(params=p, trades=tr,
                            is_m=metrics(tr[tr["entry_time"] < IS_END]),
                            oos_m=metrics(tr[tr["entry_time"] >= IS_END])))
    if not results:
        out[name] = dict(verdict="NO_SIGNALS")
        continue

    chosen = plateau_pick(results)
    is_m, oos_m = chosen["is_m"], chosen["oos_m"]
    cons_is = conservative_EV_R(is_m)
    evs = [r["is_m"]["EV_R"] for r in results]
    grid_stats = dict(n_configs=len(results),
                      pct_positive=float(np.mean([e > 0 for e in evs])),
                      ev_min=round(min(evs), 3), ev_max=round(max(evs), 3),
                      ev_median=round(float(np.median(evs)), 3))

    wf = []
    for tr_s, tr_e, te_e in wf_windows():
        cands = []
        for r in results:
            sub = r["trades"][(r["trades"]["entry_time"] >= tr_s)
                              & (r["trades"]["entry_time"] < tr_e)]
            if len(sub) >= 8:
                cands.append(dict(params=r["params"], trades=r["trades"], is_m=metrics(sub)))
        if not cands:
            continue
        pick = plateau_pick(cands)
        test = pick["trades"][(pick["trades"]["entry_time"] >= tr_e)
                              & (pick["trades"]["entry_time"] < te_e)]
        m = metrics(test)
        if m.get("n", 0) > 0:
            wf.append(dict(train=f"{tr_s.date()}..{tr_e.date()}", test_end=str(te_e.date()),
                           n=m["n"], EV_R=round(m["EV_R"], 3), total_R=round(m["total_R"], 1)))
    wf_pos = sum(1 for w in wf if w["EV_R"] > 0)
    wf_total = sum(w["total_R"] for w in wf)

    stress_m = metrics(gen(name, chosen["params"], CostModel(**STRESS)))
    ci_lo = oos_ci_lower(chosen["trades"])

    checks = {
        f"sample_size(IS)>={MIN_N[name]}": is_m.get("n", 0) >= MIN_N[name],
        "IS_EV_R>=0.15": is_m.get("EV_R", -9) >= 0.15,
        "IS_conservative>=0.05": (cons_is or -9) >= 0.05,
        "IS_PF>=1.3": is_m.get("PF", 0) >= 1.3,
        "top5_share<0.5": (is_m.get("top5_profit_share") or 1) < 0.5,
        "OOS_EV_R>0": oos_m.get("EV_R", -9) > 0,
        "OOS_degradation<50%": (oos_m.get("EV_R", -9) >= 0.5 * is_m.get("EV_R", 9)
                                if is_m.get("EV_R", 0) > 0 else False),
        "OOS_95CI_lower>0": ci_lo > 0,
        "WF>=4windows": len(wf) >= 4,
        "WF_75%_positive": wf_pos >= 0.75 * len(wf) if wf else False,
        "WF_total_R>0": wf_total > 0,
        "STRESS_EV_R>=0": stress_m.get("EV_R", -9) >= 0,
    }
    verdict = "PASS_ALL" if all(checks.values()) else "FAIL"

    entry = dict(chosen_params=chosen["params"], grid_stats=grid_stats,
                 IS=is_m, IS_conservative_EV_R=round(cons_is, 3) if cons_is == cons_is else None,
                 OOS=oos_m, OOS_95CI_lower=round(ci_lo, 3),
                 walk_forward=wf, wf_positive_windows=f"{wf_pos}/{len(wf)}",
                 wf_total_R=round(wf_total, 1), stress=stress_m,
                 checks=checks, verdict=verdict)

    # C018 感度分析: 介入日除外なし(ライブ最悪ケース)
    if name == "C018":
        tr_noex = gen(name, chosen["params"], cost, intervention_excl=False)
        entry["sensitivity_no_intervention_excl"] = dict(
            IS=metrics(tr_noex[tr_noex["entry_time"] < IS_END]),
            OOS=metrics(tr_noex[tr_noex["entry_time"] >= IS_END]))

    out[name] = entry
    chosen["trades"].to_csv(ROOT / "research" / f"trades_{name}.csv", index=False)
    et = chosen["trades"]["entry_time"]
    print(f"{name}: IS n={is_m.get('n')} EV_R={is_m.get('EV_R', 0):.3f} cons={cons_is:.3f} "
          f"OOS n={oos_m.get('n')} EV_R={oos_m.get('EV_R', 0):.3f} CI_lo={ci_lo:.3f} "
          f"WF {wf_pos}/{len(wf)} total={wf_total:.1f} stress={stress_m.get('EV_R', 0):.3f} -> {verdict}")
    print("grid:", grid_stats)
    print("entry UTC時刻分布(時):", sorted(et.dt.hour.unique()))


def default(x):
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.floating):
        return float(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return str(x)


(ROOT / "research" / "backtest_batch3_results.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1, default=default), encoding="utf-8")
print("\nsaved research/backtest_batch3_results.json")

# -*- coding: utf-8 -*-
"""第2陣バックテスト実行(C009V2 / C005)
パイプライン・閾値・プラトー選択は第1陣(runner.py)と同一。
データ衛生: パラメータ選択はIS成績のみ(OOSは選択後の1回評価)。
出力: research/backtest_batch2_results.json
"""
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

from engine import (CostModel, STRESS, conservative_EV_R, load_data,
                    load_event_windows, make_event_mask, metrics, simulate)
from runner import IS_END, plateau_pick, wf_windows
import strategies_batch2 as st2

ROOT = Path(__file__).resolve().parents[2]
MIN_N = {"C009V2": 60, "C005": 100}

GRIDS = {
    "C009V2": [dict(gate_type=g, gate_thr=t, sl_atr=sa, tp_atr=ta)
               for g, thrs in [("adx", [20, 25]), ("slope", [0.5, 0.8]), ("er", [0.30, 0.40])]
               for t in thrs
               for sa, ta in itertools.product([1.0, 1.4], [2.0, 2.5])],
    "C005": [dict(sl_pips=sl, tp_mult=tm, trend_filter=tf)
             for sl, tm, tf in itertools.product([12, 18], [1.0, 1.5], [True, False])],
}
GEN = {"C009V2": st2.c009v2_entries, "C005": st2.c005_entries}


def main():
    df = load_data()
    mask = make_event_mask(df, load_event_windows())
    daily = st2.build_daily_v2(df)
    base_cost = CostModel()
    out = {}

    for name, grid in GRIDS.items():
        print(f"\n=== {name}: grid={len(grid)} ===", flush=True)
        results = []
        for p in grid:
            trades = simulate(df, GEN[name](df, mask, daily=daily, **p), base_cost)
            if len(trades) == 0:
                continue
            results.append(dict(params=p, trades=trades,
                                is_m=metrics(trades[trades["entry_time"] < IS_END]),
                                oos_m=metrics(trades[trades["entry_time"] >= IS_END])))
        if not results:
            out[name] = dict(verdict="NO_SIGNALS")
            continue

        chosen = plateau_pick(results)
        is_m, oos_m = chosen["is_m"], chosen["oos_m"]
        cons_is, cons_oos = conservative_EV_R(is_m), conservative_EV_R(oos_m)
        evs = [r["is_m"]["EV_R"] for r in results]
        grid_stats = dict(n_configs=len(results),
                          pct_positive=float(np.mean([e > 0 for e in evs])),
                          ev_min=round(min(evs), 3), ev_max=round(max(evs), 3),
                          ev_median=round(float(np.median(evs)), 3))

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
                wf.append(dict(train=f"{tr_s.date()}..{tr_e.date()}", test_end=str(te_e.date()),
                               n=m["n"], EV_R=round(m["EV_R"], 3), total_R=round(m["total_R"], 1)))
        wf_pos = sum(1 for w in wf if w["EV_R"] > 0)
        wf_total = sum(w["total_R"] for w in wf)

        stress_m = metrics(simulate(df, GEN[name](df, mask, daily=daily, **chosen["params"]),
                                    CostModel(**STRESS)))

        checks = {
            "sample_size(IS)": is_m.get("n", 0) >= MIN_N[name],
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
        out[name] = dict(chosen_params=chosen["params"], grid_stats=grid_stats,
                         IS=is_m, IS_conservative_EV_R=round(cons_is, 3) if cons_is == cons_is else None,
                         OOS=oos_m, OOS_conservative_EV_R=round(cons_oos, 3) if cons_oos == cons_oos else None,
                         walk_forward=wf, wf_positive_windows=f"{wf_pos}/{len(wf)}",
                         wf_total_R=round(wf_total, 1), stress=stress_m,
                         checks=checks, verdict=verdict)
        print(f"{name}: IS n={is_m.get('n')} EV_R={is_m.get('EV_R', 0):.3f} cons={cons_is:.3f} "
              f"OOS n={oos_m.get('n')} EV_R={oos_m.get('EV_R', 0):.3f} "
              f"WF {wf_pos}/{len(wf)} stress={stress_m.get('EV_R', 0):.3f} -> {verdict}", flush=True)
        chosen["trades"].to_csv(ROOT / "research" / f"trades_{name}.csv", index=False)

    def default(o):
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.bool_):
            return bool(o)
        return str(o)

    (ROOT / "research" / "backtest_batch2_results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=default), encoding="utf-8")
    print("\nsaved research/backtest_batch2_results.json")


if __name__ == "__main__":
    main()

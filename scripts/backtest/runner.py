# -*- coding: utf-8 -*-
"""第1陣バックテスト実行(docs/04パイプライン: BACKTEST→OOS→WF→STRESS)
- IS: 2023-01-01〜2025-06-30 / OOS: 2025-07-01〜2026-06-26
- パラメータ選択はIS成績のみ使用。ピークでなくプラトー(上位30%の中央値)を採用
- WF: 訓練6ヶ月→検証3ヶ月、3ヶ月ステップ(訓練内で同じプラトー選択を実施)
- STRESS: スプレッド×2、スリッページ×3、AIコスト×1.5、約定遅延+1バー
出力: research/backtest_batch1_results.json / .md
"""
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

from engine import (CostModel, STRESS, conservative_EV_R, load_data,
                    load_event_windows, make_event_mask, metrics, simulate)
import strategies_batch1 as st

ROOT = Path(__file__).resolve().parents[2]
IS_END = pd.Timestamp("2025-07-01", tz="UTC")
MIN_N = {"C001": 60, "C003": 100, "C009": 60}   # docs/04: 低頻度は60(3年+)、通常100

GRIDS = {
    "C001": [dict(entry_jst_min=em, sl_pips=sl, tp_pips=tp)
             for em, sl, tp in itertools.product([540, 555], [10, 15, 20], [None, 12])],
    "C003": [dict(buffer_pips=b, sl_mode=sm, tp_mode=tm, tp_k=0.7)
             for b, sm, tm in itertools.product([2, 5], ["range_mid", "fixed"], ["range", "time"])],
    "C009": [dict(sl_atr=sa, tp_atr=ta, require_close_above=rc)
             for sa, ta, rc in itertools.product([1.0, 1.4], [1.5, 2.0, 2.5], [True, False])],
}

GEN = {"C001": st.c001_entries, "C003": st.c003_entries, "C009": st.c009_entries}


def run_param(name, df, mask, params, cost, daily=None):
    kw = dict(params)
    if name == "C009":
        kw["daily"] = daily
    entries = GEN[name](df, mask, **kw)
    return simulate(df, entries, cost)


def plateau_pick(results):
    """IS EV_R上位30%(最低3件)の中から中央値の設定を選ぶ(ピーク回避)"""
    ok = [r for r in results if r["is_m"].get("n", 0) > 0]
    ok.sort(key=lambda r: r["is_m"]["EV_R"], reverse=True)
    top = ok[:max(3, int(np.ceil(len(ok) * 0.3)))]
    return top[len(top) // 2]


def wf_windows():
    wins = []
    t = pd.Timestamp("2023-01-01", tz="UTC")
    end = pd.Timestamp("2026-06-27", tz="UTC")
    while True:
        tr_s, tr_e = t, t + pd.DateOffset(months=6)
        te_e = tr_e + pd.DateOffset(months=3)
        if te_e > end:
            break
        wins.append((tr_s, tr_e, te_e))
        t += pd.DateOffset(months=3)
    return wins


def main():
    df = load_data()
    mask = make_event_mask(df, load_event_windows())
    print(f"data={len(df)} bars, event-excluded={mask.mean() * 100:.1f}%")
    daily = st.build_daily(df)
    base_cost = CostModel()
    out = {}

    for name, grid in GRIDS.items():
        print(f"\n=== {name}: grid={len(grid)} ===")
        results = []
        for p in grid:
            tr = run_param(name, df, mask, p, base_cost, daily)
            if len(tr) == 0:
                continue
            is_tr = tr[tr["entry_time"] < IS_END]
            oos_tr = tr[tr["entry_time"] >= IS_END]
            results.append(dict(params=p, trades=tr,
                                is_m=metrics(is_tr), oos_m=metrics(oos_tr)))
        if not results:
            out[name] = dict(verdict="NO_SIGNALS")
            continue

        chosen = plateau_pick(results)
        is_m, oos_m = chosen["is_m"], chosen["oos_m"]
        cons_is = conservative_EV_R(is_m)
        cons_oos = conservative_EV_R(oos_m)

        # グリッド全体の頑健性: プラス設定の割合、EV_R分布
        evs = [r["is_m"]["EV_R"] for r in results]
        grid_stats = dict(n_configs=len(results),
                          pct_positive=float(np.mean([e > 0 for e in evs])),
                          ev_min=round(min(evs), 3), ev_max=round(max(evs), 3),
                          ev_median=round(float(np.median(evs)), 3))

        # ウォークフォワード(選択はプラトー方式を各訓練窓で再実施)
        wf = []
        for tr_s, tr_e, te_e in wf_windows():
            cands = []
            for r in results:
                t_tr = r["trades"]
                sub = t_tr[(t_tr["entry_time"] >= tr_s) & (t_tr["entry_time"] < tr_e)]
                if len(sub) >= 8:
                    cands.append(dict(params=r["params"], trades=r["trades"],
                                      is_m=metrics(sub)))
            if not cands:
                continue
            pick = plateau_pick(cands)
            t_all = pick["trades"]
            test = t_all[(t_all["entry_time"] >= tr_e) & (t_all["entry_time"] < te_e)]
            m = metrics(test)
            if m.get("n", 0) > 0:
                wf.append(dict(train=f"{tr_s.date()}..{tr_e.date()}",
                               test_end=str(te_e.date()), n=m["n"],
                               EV_R=round(m["EV_R"], 3), total_R=round(m["total_R"], 1)))
        wf_pos = sum(1 for w in wf if w["EV_R"] > 0)
        wf_total = sum(w["total_R"] for w in wf)

        # ストレステスト(選択パラメータ・全期間)
        stress_tr = run_param(name, df, mask, chosen["params"], CostModel(**STRESS), daily)
        stress_m = metrics(stress_tr)

        # 合否(docs/04 + docs/03閾値)
        min_n = MIN_N[name]
        checks = {
            "sample_size(IS)": is_m.get("n", 0) >= min_n,
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

        out[name] = dict(
            chosen_params={k: v for k, v in chosen["params"].items()},
            grid_stats=grid_stats,
            IS=is_m, IS_conservative_EV_R=round(cons_is, 3) if cons_is == cons_is else None,
            OOS=oos_m, OOS_conservative_EV_R=round(cons_oos, 3) if cons_oos == cons_oos else None,
            walk_forward=wf, wf_positive_windows=f"{wf_pos}/{len(wf)}",
            wf_total_R=round(wf_total, 1),
            stress=stress_m, checks=checks, verdict=verdict,
        )
        print(f"{name}: IS n={is_m.get('n')} EV_R={is_m.get('EV_R', 0):.3f} "
              f"OOS n={oos_m.get('n')} EV_R={oos_m.get('EV_R', 0):.3f} "
              f"WF {wf_pos}/{len(wf)} stress={stress_m.get('EV_R', 0):.3f} -> {verdict}")

        # 取引明細も保存(Skeptic審査用)
        chosen["trades"].to_csv(ROOT / "research" / f"trades_{name}.csv", index=False)

    def default(o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return float(o)
        if isinstance(o, (np.bool_,)):
            return bool(o)
        return str(o)

    (ROOT / "research" / "backtest_batch1_results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=default), encoding="utf-8")
    print("\nsaved research/backtest_batch1_results.json")


if __name__ == "__main__":
    main()

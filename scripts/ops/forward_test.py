# -*- coding: utf-8 -*-
"""前進検証(ペーパー)エンジン
RESEARCH_ONLY凍結中のC009/C009v2を、バックテストで一切使用していない
新データ(2026-06-27以降、Dukascopy BIDキャンドル)で機械的に追跡する。

- パラメータは凍結値固定(backtest_batch1/2_results.jsonのchosen_params。変更禁止)
- コストは保守値(engine.CostModel)。イベント除外は2026年カレンダー(検証済み)を適用
- 出力: logs/forward/forward_trades.csv / logs/forward/summary.md
- 毎回フル再計算(冪等)。データ末尾で未決済の取引はOPENとして除外集計
実行: python3 scripts/ops/forward_test.py
"""
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "backtest"))
sys.path.insert(0, str(ROOT / "scripts" / "data"))

from engine import CostModel, load_event_windows, make_event_mask, metrics, simulate  # noqa: E402
from strategies_batch1 import build_daily, c009_entries  # noqa: E402
from strategies_batch2 import build_daily_v2, c009v2_entries  # noqa: E402

FORWARD_START = pd.Timestamp("2026-06-27", tz="UTC")   # 凍結データセットの終端
WARMUP_START = pd.Timestamp("2026-02-01", tz="UTC")    # MA20/ATR14等のウォームアップ
FROZEN = {
    "C009": dict(sl_atr=1.0, tp_atr=2.5, require_close_above=True),
    "C009V2": dict(gate_type="er", gate_thr=0.4, sl_atr=1.0, tp_atr=2.0),
}
OUT_DIR = ROOT / "logs" / "forward"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def update_forward_data() -> pd.DataFrame | None:
    """Dukascopyから FORWARD_START〜昨日 のM1 BIDキャンドルを取得(キャッシュ利用)"""
    from download_dukascopy import fetch_day  # 既存実装を再利用
    end = dt.date.today() - dt.timedelta(days=1)
    d = FORWARD_START.date()
    days = []
    while d <= end:
        if d.weekday() != 5:
            days.append(d)
        d += dt.timedelta(days=1)
    rows, failed = [], []
    for day in days:
        day, r = fetch_day(day)
        if r is None:
            failed.append(day)
        else:
            rows.extend(r)
    if not rows:
        print(f"forward data: 取得0行(failed={len(failed)})", flush=True)
        return None
    df = pd.DataFrame(rows, columns=["time_utc", "open", "high", "low", "close", "volume"])
    df = df.drop(columns=["volume"]).sort_values("time_utc").drop_duplicates("time_utc")
    df = df[df["time_utc"] >= FORWARD_START].reset_index(drop=True)
    df.to_parquet(ROOT / "data" / "usdjpy_m1_forward.parquet", index=False)
    if failed:
        print(f"forward data: failed days={[str(x) for x in failed]}", flush=True)
    return df


def build_df() -> pd.DataFrame:
    hist = pd.read_parquet(ROOT / "data" / "usdjpy_m1.parquet")
    hist = hist[["time_utc", "open", "high", "low", "close"]]
    fwd_path = ROOT / "data" / "usdjpy_m1_forward.parquet"
    fwd = update_forward_data()
    if fwd is None and fwd_path.exists():
        fwd = pd.read_parquet(fwd_path)
    frames = [hist[hist["time_utc"] >= WARMUP_START]]
    if fwd is not None and len(fwd):
        frames.append(fwd)
    df = (pd.concat(frames).sort_values("time_utc")
          .drop_duplicates("time_utc", keep="first").reset_index(drop=True))
    t = df["time_utc"]
    df["utc_min"] = (t.dt.hour * 60 + t.dt.minute).astype(np.int32)
    jst = t + pd.Timedelta(hours=9)
    df["jst_date"] = jst.dt.date
    df["jst_min"] = (jst.dt.hour * 60 + jst.dt.minute).astype(np.int32)
    return df


def main():
    df = build_df()
    data_end = df["time_utc"].iloc[-1]
    if data_end <= FORWARD_START:
        print("新データなし。終了")
        return
    mask = make_event_mask(df, load_event_windows())
    daily2 = build_daily_v2(df)
    cost = CostModel()

    all_tr = {}
    for name, params in FROZEN.items():
        if name == "C009":
            entries = c009_entries(df, mask, daily=daily2, **params)
        else:
            entries = c009v2_entries(df, mask, daily=daily2, **params)
        tr = simulate(df, entries, cost)
        if len(tr):
            tr = tr[tr["entry_time"] >= FORWARD_START].copy()
            # データ末尾でのTIME決済=未決済(censored)扱い
            tr["open_censored"] = (tr["reason"] == "TIME") & \
                (tr["exit_time"] >= data_end - pd.Timedelta(hours=2))
        all_tr[name] = tr

    lines = [f"# 前進検証サマリー(自動生成)",
             f"", f"- 実行日時(UTC): {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M}",
             f"- 前進期間: {FORWARD_START.date()} 〜 {data_end:%Y-%m-%d %H:%M} (UTC)",
             f"- コスト: 保守値(spread {cost.spread_pips}p + slip {cost.slip_pips}p×2 + AI {cost.ai_cost_R}R)",
             f"- パラメータ: 凍結値固定(変更禁止)", ""]
    for name, tr in all_tr.items():
        closed = tr[~tr["open_censored"]] if len(tr) else tr
        m = metrics(closed)
        ref = {"C009": "IS +0.186 / OOS -0.028(参考)", "C009V2": "IS +0.217 / OOS -0.067"}[name]
        lines += [f"## {name}(backtest: {ref})",
                  f"- 前進シグナル: {len(tr)}件(確定 {len(closed)}件、未決済 {int(tr['open_censored'].sum()) if len(tr) else 0}件)"]
        if m.get("n", 0) > 0:
            lines += [f"- 確定EV_R: **{m['EV_R']:+.3f}**(n={m['n']}, 勝率{m['win_rate']:.0%}, 合計{m['total_R']:+.1f}R)"]
        lines += [""]
        if len(tr):
            cols = ["entry_time", "exit_time", "dir", "entry", "exit", "reason", "R", "open_censored"]
            tr[cols].to_csv(OUT_DIR / f"forward_{name}.csv", index=False)
    lines += ["## 判定基準(docs/04 PAPER_TRADE)",
              "- 最低20シグナルで評価。実測EV_Rがバックテスト値の50%以上+ルール違反0件で昇格審査",
              "- OOSがマイナスだった両候補が前進でもマイナスなら、RESEARCH_ONLY→REJECTEDへ降格を検討", ""]
    (OUT_DIR / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

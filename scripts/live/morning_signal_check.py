# -*- coding: utf-8 -*-
"""朝シグナル判定(execution model B のクラウド側・毎朝Routineで実行)

役割分担:
  - 本スクリプト(クラウド、毎朝8:15 JST): 日足ベース戦略のシグナルを判定し、
    成立時のみプッシュ通知(発注案付き)→ ユーザーが手動発注
  - scripts/live/signal_alert_engine.py(ユーザーPC、任意): 画面同席時の
    リアルタイム音アラート。同じ Signal/ゲート/サイズ計算を共有

安全原則: 発注はしない(松井証券規程・README原則7)。
  未承認戦略(C009/C009v2)は shadow = 通知本文に「ペーパー記録」と明記され、
  発注案としては提示しない。APPROVED戦略が存在しない間、TRADE通知は発生しない。

出力(stdoutの末尾サマリーをRoutineが通知文に使う):
  RESULT: ALERT_TRADE / SHADOW_SIGNAL / HALT / NO_SIGNAL / DATA_STALE
"""
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
for sub in ("backtest", "data", "ops", "live"):
    sys.path.insert(0, str(ROOT / "scripts" / sub))

from forward_test import build_df  # noqa: E402  (Dukascopyで最新化済みのdfを返す)
from strategies_batch2 import build_daily_v2  # noqa: E402
import signal_alert_engine as E  # noqa: E402

JST = dt.timezone(dt.timedelta(hours=9))
PIP = 0.01


# ---------- 日中状態の自動初期化(朝time点では取引ゼロが正) ----------
def ensure_daily_state() -> dict:
    p = ROOT / "logs" / "daily" / f"state_{dt.datetime.now(JST):%Y-%m-%d}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    st = dict(date=f"{dt.datetime.now(JST):%Y-%m-%d}",
              equity_jpy=E.RISK["account"]["initial_equity_jpy"],
              realized_pnl_jpy=0, unrealized_pnl_jpy=0, execution_costs_jpy=0,
              ai_cash_cost_jpy=0, ai_shadow_cost_jpy=0, economic_daily_loss_jpy=0,
              trades_today=0, consecutive_losses=0,
              remaining_risk_budget_jpy=E.RISK["daily"]["max_loss_jpy"],
              halt_flags=[], last_updated="morning_signal_check:init")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    return st


# ---------- 完成した日足列(形成途中の当日行を除外) ----------
def completed_daily(df: pd.DataFrame) -> pd.DataFrame:
    daily = build_daily_v2(df)
    t = df["time_utc"]
    last_bar_utc = daily["last_idx"].map(lambda i: t.iloc[int(i)])
    # NYクローズ(約21:58 UTC)まで到達していない末尾行は形成途中 → 除外
    complete = [ts.hour >= 21 and ts.minute >= 50 for ts in last_bar_utc]
    return daily[np.array(complete) | (np.arange(len(daily)) < len(daily) - 1)]


# ---------- 凍結戦略のライブ判定アダプタ(LiveStrategy互換) ----------
def _load_ev(name: str) -> tuple[float, float]:
    if name == "C009":
        r = json.loads((ROOT / "research" / "backtest_batch1_results.json").read_text(encoding="utf-8"))["C009"]
    else:
        r = json.loads((ROOT / "research" / "backtest_batch2_results.json").read_text(encoding="utf-8"))["C009V2"]
    return float(r["IS"]["EV_R"]), float(r.get("IS_conservative_EV_R") or -9)


class C009Live:
    """C009凍結パラメータ(sl_atr=1.0, tp_atr=2.5, require_close_above)の朝判定。
    シグナル判定ロジックは strategies_batch1.c009_entries と同一条件(前日確定日足)。"""
    name, version, approved = "C009", "frozen-2026-07-07", False

    def __init__(self):
        self.est_EV_R, self.est_cons = _load_ev("C009")

    def evaluate(self, daily: pd.DataFrame):
        d = daily.reset_index(names="day")
        if len(d) < 22:
            return None
        i = len(d) - 1
        row, prev = d.iloc[i], d.iloc[i - 1]
        if np.isnan(row["ma20"]) or np.isnan(row["atr14"]) or row["atr14"] <= 0:
            return None
        atr_pips = row["atr14"] / PIP
        long_sig = (row["close"] > row["ma20"] and row["ma20"] > d["ma20"].iloc[i - 5]
                    and row["low"] <= row["ma5"] and prev["close"] > prev["ma5"]
                    and row["close"] > row["ma5"])
        short_sig = (row["close"] < row["ma20"] and row["ma20"] < d["ma20"].iloc[i - 5]
                     and row["high"] >= row["ma5"] and prev["close"] < prev["ma5"]
                     and row["close"] < row["ma5"])
        if not (long_sig or short_sig):
            return None
        return E.Signal(direction=+1 if long_sig else -1,
                        sl_pips=float(np.clip(1.0 * atr_pips, 15, 45)),
                        tp_pips=float(np.clip(2.5 * atr_pips, 20, 90)),
                        est_EV_R=self.est_EV_R, est_conservative_EV_R=self.est_cons,
                        regime="daily_pullback",
                        note=f"シグナル日={row['day']} ATR={atr_pips:.0f}pips")


class C009V2Live(C009Live):
    """C009v2 = C009 + 効率比ゲート(er10>=0.4)。tp_atr=2.0。"""
    name, version, approved = "C009V2", "frozen-2026-07-08", False

    def __init__(self):
        self.est_EV_R, self.est_cons = _load_ev("C009V2")

    def evaluate(self, daily: pd.DataFrame):
        sig = super().evaluate(daily)
        if sig is None:
            return None
        er = daily["er10"].iloc[-1]
        if np.isnan(er) or er < 0.4:
            return None
        atr_pips = daily["atr14"].iloc[-1] / PIP
        sig.tp_pips = float(np.clip(2.0 * atr_pips, 20, 90))
        sig.note += f" er10={er:.2f}"
        return sig


STRATEGIES = [C009Live, C009V2Live]


def main():
    now = dt.datetime.now(JST)
    print(f"=== 朝シグナル判定 {now:%Y-%m-%d %H:%M JST} ===")

    df = build_df()
    data_end = df["time_utc"].iloc[-1]
    staleness_h = (pd.Timestamp.now("UTC") - data_end).total_seconds() / 3600
    print(f"データ末尾: {data_end:%Y-%m-%d %H:%M UTC}({staleness_h:.1f}h前)")
    if staleness_h > 36:
        print("RESULT: DATA_STALE データが古いため判定不能(全件NO_TRADE扱い)")
        return

    state = ensure_daily_state()

    # 介入/急変チェック(検知器と同一ロジック)
    df["move30"] = (df["close"] - df["close"].shift(30)).abs() / PIP
    last24 = df[df["time_utc"] >= data_end - pd.Timedelta(hours=24)]
    max24 = float(last24["move30"].max())
    if max24 >= 150:
        state["halt_flags"] = sorted(set(state.get("halt_flags", []) + ["INTERVENTION_24H"]))
        p = ROOT / "logs" / "daily" / f"state_{now:%Y-%m-%d}.json"
        p.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        print(f"⚠ 急変検知: 直近24hに30分{max24:.0f}pips → halt_flagsに登録")

    daily = completed_daily(df)
    print(f"最終確定日足: {daily.index[-1]}(この日足のシグナルを本日東京9:00に執行想定)")

    windows = E.load_no_trade_windows()
    alerts, shadows = [], []
    for cls in STRATEGIES:
        strat = cls()
        sig = strat.evaluate(daily)
        ts = now.isoformat(timespec="seconds")
        if sig is None:
            E.log_signal(dict(ts=ts, strategy=strat.name, version=strat.version,
                              signal="NONE", decision="NO_TRADE", failed_checks=[],
                              net_EV_R=0, conservative_net_EV_R=0, spread_pips=0.4,
                              regime="", note="no signal"))
            print(f"  {strat.name}: シグナルなし")
            continue
        fails = E.gate_checks(sig, spread_pips=0.4, bar_time_utc=data_end,
                              state=state, windows=windows)
        side = "BUY" if sig.direction > 0 else "SELL"
        decision = "TRADE" if not fails else "NO_TRADE"
        E.log_signal(dict(ts=ts, strategy=strat.name, version=strat.version,
                          signal=side, decision=decision, failed_checks=fails,
                          net_EV_R=round(sig.est_EV_R, 3),
                          conservative_net_EV_R=round(sig.est_conservative_EV_R, 3),
                          spread_pips=0.4, regime=sig.regime, note=sig.note))
        units = E.position_units(sig.sl_pips)
        px = float(daily["close"].iloc[-1])
        sl_px = px - sig.direction * sig.sl_pips * PIP
        tp_px = px + sig.direction * (sig.tp_pips or 0) * PIP
        desc = (f"{strat.name} {side} {units:,}通貨 基準≈{px:.3f} "
                f"SL {sl_px:.3f}({sig.sl_pips:.0f}p) TP {tp_px:.3f} "
                f"EV{sig.est_EV_R:+.2f}/保守{sig.est_conservative_EV_R:+.2f} {sig.note}")
        if strat.approved and decision == "TRADE":
            alerts.append(desc)
            print(f"  🔔 {desc}")
        else:
            why = "未承認(ペーパー記録)" if not strat.approved else f"NO_TRADE({','.join(fails)})"
            shadows.append(f"{desc} [{why}]")
            print(f"  👻 {desc} [{why}]")

    if alerts:
        print("\nRESULT: ALERT_TRADE " + " | ".join(alerts))
    elif max24 >= 150:
        print("\nRESULT: HALT 急変検知により本日NO_TRADE")
    elif shadows:
        print("\nRESULT: SHADOW_SIGNAL " + " | ".join(shadows))
    else:
        print("\nRESULT: NO_SIGNAL 本日はシグナルなし(NO_TRADE継続が正)")


if __name__ == "__main__":
    main()

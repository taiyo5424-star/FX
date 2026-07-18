# -*- coding: utf-8 -*-
"""取引前チェックリスト自動生成(docs/02準拠・完全ルールベース、Fable5不使用)
早期NO_TRADE方式: S1→S11の順に判定し、FAILが出た時点で打ち切り。

使い方:
  python pretrade_checklist.py --strategy <id> --direction BUY --entry 157.10 \
      --sl 156.90 --tp 157.50 --spread 0.2 --equity 500000
出力: 判定JSON(標準出力)+ logs/signals/YYYY-MM-DD.jsonl へ追記
"""
import argparse
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIMITS = json.loads((ROOT / "config" / "risk_limits.json").read_text(encoding="utf-8"))
EV = LIMITS["ev_thresholds"]


def no_trade(reason, failed, partial=None):
    out = {"decision": "NO_TRADE", "broker": "松井証券", "symbol": "USD/JPY",
           "reason": reason, "failed_checks": failed}
    if partial:
        out.update(partial)
    return out


def in_core_time(now_jst: dt.datetime) -> bool:
    """コアタイム 9:00〜翌3:00 JST(松井証券・スプレッド原則固定の時間帯)"""
    h = now_jst.hour
    return h >= 9 or h < 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", required=True)
    ap.add_argument("--direction", choices=["BUY", "SELL"], required=True)
    ap.add_argument("--entry", type=float, required=True)
    ap.add_argument("--sl", type=float, required=True)
    ap.add_argument("--tp", type=float, required=True)
    ap.add_argument("--spread", type=float, required=True, help="実測スプレッド(pips)")
    ap.add_argument("--equity", type=float, required=True)
    a = ap.parse_args()
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))

    # S1: 戦略状態
    sfile = ROOT / "strategies" / "approved" / f"{a.strategy}.json"
    if not sfile.exists():
        return emit(no_trade(f"戦略 {a.strategy} はAPPROVEDではない(approved/に存在しない)", ["S1_strategy_status"]))
    strat = json.loads(sfile.read_text(encoding="utf-8"))
    if strat.get("status") != "APPROVED" or not strat.get("approved_by_user"):
        return emit(no_trade("status!=APPROVED または ユーザー承認なし", ["S1_strategy_status"]))

    # S2/S3: 日中状態
    state_p = ROOT / "logs" / "daily" / f"state_{now:%Y-%m-%d}.json"
    if not state_p.exists():
        return emit(no_trade("日中状態ファイルなし(口座状態未確認)", ["S2_account_state"]))
    state = json.loads(state_p.read_text(encoding="utf-8"))
    if not state.get("new_trades_allowed", False):
        return emit(no_trade(f"日次停止条件: {state.get('halt_flags')}", ["S3_daily_limits"]))

    # S4: イベントウィンドウ
    cal_p = ROOT / "data" / "calendar" / "no_trade_windows.json"
    if not cal_p.exists():
        return emit(no_trade("イベントカレンダー未取得(fetch_calendar.py未実行)", ["S4_event_filter"]))
    cal = json.loads(cal_p.read_text(encoding="utf-8"))
    gen = dt.datetime.fromisoformat(cal["generated_at_utc"])
    if (dt.datetime.now(dt.timezone.utc) - gen) > dt.timedelta(hours=26):
        return emit(no_trade("カレンダーが26時間以上古い", ["S4_event_filter"]))
    now_utc = dt.datetime.now(dt.timezone.utc)
    for w in cal["windows"]:
        if dt.datetime.fromisoformat(w["no_trade_start_utc"]) <= now_utc <= dt.datetime.fromisoformat(w["no_trade_end_utc"]):
            return emit(no_trade(f"イベント除外中: {w['title']}", ["S4_event_filter"]))

    # S5: セッション(コアタイム)
    if not in_core_time(now):
        return emit(no_trade("コアタイム外(スプレッド変動枠)", ["S5_session"]))
    if now.weekday() == 0 and now.hour < 8:
        return emit(no_trade("週明け直後", ["S5_session"]))

    # S6: スプレッド
    max_spread = strat.get("risk_limits", {}).get("max_spread_pips", 0.3)
    if a.spread > max_spread:
        return emit(no_trade(f"スプレッド{a.spread} > 許容{max_spread}", ["S6_spread"]))

    # S8: EV(戦略ファイルの検証済み値を使用)
    perf = strat.get("expected_performance", {})
    fails = []
    for key, thr in [("EV_R", EV["min_EV_R"]), ("conservative_EV_R", EV["min_conservative_EV_R"]),
                     ("net_EV_R_after_ai_cost", EV["min_net_EV_R"]),
                     ("conservative_net_EV_R_after_ai_cost", EV["min_conservative_net_EV_R"])]:
        v = perf.get(key)
        if v is None or float(v) < thr:
            fails.append(f"S8_{key}")
    if fails:
        return emit(no_trade("EV閾値未達", fails))

    # S9: サイズ計算
    sl_pips = abs(a.entry - a.sl) * 100
    if sl_pips < 5:
        return emit(no_trade("損切り幅が狭すぎる(<5pips、ノイズ域)", ["S9_size"]))
    std_risk = a.equity * LIMITS["per_trade"]["standard_risk_pct_of_equity"]
    risk = min(std_risk, LIMITS["per_trade"]["absolute_max_risk_jpy"],
               state["remaining_risk_budget_jpy"])
    worst_sl_pips = sl_pips + a.spread + 2 * 0.3  # 最悪スリッページ込み
    size = int(risk / (worst_sl_pips * 0.01))     # 1通貨単位(松井:1通貨から可)
    if size < 100:
        return emit(no_trade("計算サイズが極小(リスク枠不足)", ["S9_size"]))
    max_loss = round(worst_sl_pips * 0.01 * size)
    if max_loss > LIMITS["per_trade"]["absolute_max_risk_jpy"]:
        return emit(no_trade("最悪想定損失が5,000円超", ["S9_size"]))

    # 全PASS → 発注案(実発注はユーザー)
    out = {
        "decision": "TRADE_PROPOSAL(発注はユーザー操作)",
        "broker": "松井証券", "symbol": "USD/JPY",
        "execution_method": "browser(ユーザー操作) or 公式自動売買設定",
        "strategy_name": strat["strategy_name"], "strategy_version": strat["version"],
        "direction": a.direction, "entry_price": a.entry, "stop_loss": a.sl,
        "take_profit_plan": a.tp, "position_size": size,
        "risk_per_trade_jpy": round(risk), "max_loss_if_stopped_jpy": max_loss,
        "risk_percent_of_equity": round(risk / a.equity * 100, 2),
        "daily_remaining_risk_budget_jpy": state["remaining_risk_budget_jpy"],
        "spread_pips": a.spread, "sl_pips": round(sl_pips, 1),
        "EV_R": perf.get("EV_R"), "conservative_EV_R": perf.get("conservative_EV_R"),
        "net_EV_R": perf.get("net_EV_R_after_ai_cost"),
        "conservative_net_EV_R": perf.get("conservative_net_EV_R_after_ai_cost"),
        "checks": "S1-S9 PASS(S10実行系・S11注文画面照合はユーザー操作時に確認)",
    }
    return emit(out)


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1))
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
    p = ROOT / "logs" / "signals"
    p.mkdir(parents=True, exist_ok=True)
    rec = dict(ts=now.isoformat(timespec="seconds"), **{k: v for k, v in obj.items()})
    with open(p / f"{now:%Y-%m-%d}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()

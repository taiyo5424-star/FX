# -*- coding: utf-8 -*-
"""日中状態ファイル管理(logs/daily/state_YYYY-MM-DD.json)
全取引判断の前提となる状態を管理する。読めない場合は NO_TRADE(呼び出し側の責務)。

使い方:
  python daily_state.py init --equity 500000
  python daily_state.py update --realized -1200 --unrealized -300 --ai-cash 0 --ai-shadow 50
  python daily_state.py trade-result --pnl -2400        # 取引確定時
  python daily_state.py status                          # 現在の停止判定を表示
"""
import argparse
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIMITS = json.loads((ROOT / "config" / "risk_limits.json").read_text(encoding="utf-8"))

DAILY_MAX = LIMITS["daily"]["max_loss_jpy"]          # 20000
WARN = LIMITS["daily"]["warning_stop_line_jpy"]      # 16000
MAX_TRADES = LIMITS["daily"]["max_trades"]           # 3
MAX_STREAK = LIMITS["streak_and_drawdown"]["max_consecutive_losses_before_halt"]  # 4


def today_path() -> Path:
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
    p = ROOT / "logs" / "daily"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"state_{now:%Y-%m-%d}.json"


def load() -> dict:
    p = today_path()
    if not p.exists():
        raise SystemExit(f"状態ファイルなし: {p} → 先に init を実行。判断側は NO_TRADE とすること")
    return json.loads(p.read_text(encoding="utf-8"))


def save(s: dict):
    s["last_updated"] = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="seconds")
    recompute(s)
    today_path().write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")


def recompute(s: dict):
    loss = -(min(s["realized_pnl_jpy"], 0) + min(s["unrealized_pnl_jpy"], 0)) \
           + s["execution_costs_jpy"] + s["ai_cash_cost_jpy"] + s["tool_cost_jpy"]
    s["economic_daily_loss_jpy"] = round(loss)
    flags = []
    if loss >= DAILY_MAX:
        flags.append("DAILY_HARD_STOP_20000")
    elif loss >= WARN:
        flags.append("DAILY_WARNING_16000")
    if s["trades_today"] >= MAX_TRADES:
        flags.append("MAX_TRADES_REACHED")
    if s["consecutive_losses"] >= MAX_STREAK:
        flags.append("LOSING_STREAK_HALT")
    s["halt_flags"] = flags
    s["new_trades_allowed"] = len(flags) == 0
    s["remaining_risk_budget_jpy"] = max(0, WARN - round(loss))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_init = sub.add_parser("init")
    p_init.add_argument("--equity", type=float, required=True)
    p_up = sub.add_parser("update")
    p_up.add_argument("--realized", type=float)
    p_up.add_argument("--unrealized", type=float)
    p_up.add_argument("--exec-costs", type=float)
    p_up.add_argument("--ai-cash", type=float)
    p_up.add_argument("--ai-shadow", type=float)
    p_up.add_argument("--tool-cost", type=float)
    p_tr = sub.add_parser("trade-result")
    p_tr.add_argument("--pnl", type=float, required=True)
    sub.add_parser("status")
    a = ap.parse_args()

    if a.cmd == "init":
        s = dict(date=str(dt.date.today()), equity_jpy=a.equity,
                 realized_pnl_jpy=0, unrealized_pnl_jpy=0, execution_costs_jpy=0,
                 ai_cash_cost_jpy=0, ai_shadow_cost_jpy=0, tool_cost_jpy=0,
                 trades_today=0, consecutive_losses=0)
        save(s)
        print("initialized", today_path())
    elif a.cmd == "update":
        s = load()
        for k, v in [("realized_pnl_jpy", a.realized), ("unrealized_pnl_jpy", a.unrealized),
                     ("execution_costs_jpy", a.exec_costs), ("ai_cash_cost_jpy", a.ai_cash),
                     ("ai_shadow_cost_jpy", a.ai_shadow), ("tool_cost_jpy", a.tool_cost)]:
            if v is not None:
                s[k] = v
        save(s)
        print(json.dumps(s, ensure_ascii=False, indent=1))
    elif a.cmd == "trade-result":
        s = load()
        s["trades_today"] += 1
        s["realized_pnl_jpy"] += a.pnl
        s["consecutive_losses"] = 0 if a.pnl > 0 else s["consecutive_losses"] + 1
        save(s)
        print(json.dumps(s, ensure_ascii=False, indent=1))
    else:
        s = load()
        recompute(s)
        print(json.dumps(s, ensure_ascii=False, indent=1))
        print("\n新規取引可否:", "OK" if s["new_trades_allowed"] else f"停止 {s['halt_flags']}")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""実測スプレッド記録CLI(ペーパートレード期間の観測用)
使い方(松井証券の画面を見ながらユーザーが入力、またはbid/askを引数で渡す):
  python log_spread.py 157.123 157.125
  python log_spread.py 157.123 157.125 --event
出力: logs/spreads/YYYY-MM-DD.jsonl
"""
import argparse
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def session_of(now_jst: dt.datetime) -> str:
    h = now_jst.hour
    if 9 <= h < 15:
        return "Tokyo"
    if 15 <= h < 21:
        return "London"
    if 21 <= h or h < 3:
        return "New_York"
    return "Illiquid"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bid", type=float)
    ap.add_argument("ask", type=float)
    ap.add_argument("--event", action="store_true", help="イベント時間帯フラグ")
    a = ap.parse_args()
    if a.ask < a.bid:
        raise SystemExit("ask < bid は不正です")
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
    rec = {
        "ts": now.isoformat(timespec="seconds"),
        "bid": a.bid, "ask": a.ask,
        "spread_pips": round((a.ask - a.bid) * 100, 2),
        "session": session_of(now), "event_window": a.event,
    }
    out = ROOT / "logs" / "spreads"
    out.mkdir(parents=True, exist_ok=True)
    f = out / f"{now:%Y-%m-%d}.jsonl"
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("recorded:", rec)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""経済指標カレンダー取得(ライブ運用用・毎朝実行想定)
ソース: ForexFactory公開フィード(nfs.faireconomy.media)
出力:
  data/calendar/thisweek_raw.json   … 生データキャッシュ
  data/calendar/no_trade_windows.json … USD/JPY関連の取引禁止時間帯(UTC)
ルール(docs/仕様書第15節):
  - USD/JPY関連 = 通貨がUSDまたはJPYのイベント
  - 高インパクト指標: 前後30分禁止
  - FOMC/日銀会合/中銀会見: 前後2時間禁止
Fable5不使用・完全ルールベース。
"""
import json
import datetime as dt
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
CAL = ROOT / "data" / "calendar"
CAL.mkdir(parents=True, exist_ok=True)

FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CENTRAL_BANK_KEYWORDS = ["FOMC", "Federal Funds Rate", "BOJ", "Bank of Japan",
                         "Monetary Policy", "Press Conference", "BoJ"]


def main():
    r = requests.get(FEED, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    events = r.json()
    (CAL / "thisweek_raw.json").write_text(json.dumps(events, ensure_ascii=False, indent=1), encoding="utf-8")

    windows = []
    for ev in events:
        if ev.get("country") not in ("USD", "JPY"):
            continue
        impact = ev.get("impact", "")
        title = ev.get("title", "")
        if impact != "High":
            continue
        try:
            t = dt.datetime.fromisoformat(ev["date"])  # フィードはISO形式(オフセット付き)
        except (KeyError, ValueError):
            continue
        t_utc = t.astimezone(dt.timezone.utc)
        is_cb = any(k.lower() in title.lower() for k in CENTRAL_BANK_KEYWORDS)
        pad = dt.timedelta(hours=2) if is_cb else dt.timedelta(minutes=30)
        windows.append({
            "title": title, "country": ev["country"], "impact": impact,
            "event_utc": t_utc.isoformat(),
            "no_trade_start_utc": (t_utc - pad).isoformat(),
            "no_trade_end_utc": (t_utc + pad).isoformat(),
            "central_bank": is_cb,
        })

    out = {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": FEED,
        "rule": "High impact ±30min / central bank ±2h",
        "windows": sorted(windows, key=lambda w: w["event_utc"]),
    }
    (CAL / "no_trade_windows.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"events total={len(events)} high_impact_usd_jpy={len(windows)}")
    for w in windows[:10]:
        print(" ", w["event_utc"], w["country"], w["title"], "(CB)" if w["central_bank"] else "")


if __name__ == "__main__":
    main()

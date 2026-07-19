# -*- coding: utf-8 -*-
"""Dukascopyティック(bid/ask)から時間帯別スプレッド・プロファイルを構築
URL: https://datafeed.dukascopy.com/datafeed/USDJPY/{y}/{m-1:02d}/{d:02d}/{h:02d}h_ticks.bi5
レコード: 20バイト big-endian [msオフセット(int), ask(int,×1000), bid(int,×1000),
          askVol(float), bidVol(float)]
目的:
  - コストモデル(engine.CostModel spread=0.4pips保守値)の時間帯依存の実態把握
  - 松井証券実測(ユーザー収集)が溜まるまでの参照下限値・時間帯形状の提供
注意: DukascopyはECN系のためスプレッド絶対値は松井証券と異なる。
      「時間帯ごとの相対形状」と「広がる時間帯の特定」を主目的とする。
出力: data/spread_profile.json / research/spread_profile_report.md
"""
import datetime as dt
import json
import lzma
import struct
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw_ticks"
RAW.mkdir(parents=True, exist_ok=True)

SYMBOL = "USDJPY"
POINT = 1000.0
PIP = 0.01
# 直近4週間の営業日をサンプル(全履歴は不要。現行レジームの形状が目的)
END = dt.date(2026, 7, 17)
DAYS = 28
BASE = "https://datafeed.dukascopy.com/datafeed/{sym}/{y}/{m:02d}/{d:02d}/{h:02d}h_ticks.bi5"

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0 (research; personal backtest data)"


def fetch_hour(day: dt.date, hour: int):
    cache = RAW / f"{day:%Y-%m-%d}_{hour:02d}.bi5"
    if cache.exists():
        data = cache.read_bytes()
    else:
        url = BASE.format(sym=SYMBOL, y=day.year, m=day.month - 1, d=day.day, h=hour)
        data = None
        for attempt in range(3):
            try:
                r = session.get(url, timeout=30)
                if r.status_code == 404:
                    data = b""
                    break
                r.raise_for_status()
                data = r.content
                break
            except Exception:
                time.sleep(1.5 * (attempt + 1))
        if data is None:
            return day, hour, None
        cache.write_bytes(data)
    if not data:
        return day, hour, []
    try:
        raw = lzma.decompress(data)
    except lzma.LZMAError:
        return day, hour, None
    out = []
    for off in range(0, len(raw) - 19, 20):
        ms, ask, bid, _av, _bv = struct.unpack(">3i2f", raw[off:off + 20])
        out.append((hour, (ask - bid) / POINT / PIP))  # スプレッド(pips)
    return day, hour, out


def main():
    days = []
    d = END
    while len(days) < DAYS:
        if d.weekday() < 5:
            days.append(d)
        d -= dt.timedelta(days=1)
    jobs = [(day, h) for day in days for h in range(24)]

    recs = []
    failed = 0
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(fetch_hour, day, h): (day, h) for day, h in jobs}
        for i, fut in enumerate(as_completed(futs)):
            day, hour, rows = fut.result()
            if rows is None:
                failed += 1
            else:
                for h, sp in rows:
                    recs.append((str(day), h, sp))
            if (i + 1) % 100 == 0:
                print(f"progress {i + 1}/{len(jobs)} ticks={len(recs)}", flush=True)

    df = pd.DataFrame(recs, columns=["day", "utc_hour", "spread_pips"])
    df = df[(df["spread_pips"] > 0) & (df["spread_pips"] < 20)]  # 異常値除去
    df["jst_hour"] = (df["utc_hour"] + 9) % 24
    prof = df.groupby("jst_hour")["spread_pips"].agg(
        n="count", p25=lambda x: x.quantile(.25), median="median",
        p75=lambda x: x.quantile(.75), p90=lambda x: x.quantile(.9),
        p99=lambda x: x.quantile(.99)).round(3)

    payload = dict(
        source="Dukascopy ticks", symbol=SYMBOL,
        sample_days=[str(x) for x in days], n_ticks=int(len(df)),
        failed_hour_files=failed, generated_at=str(END),
        note="ECN系スプレッド。松井証券実測の代替下限値と時間帯形状の参照用",
        by_jst_hour={int(h): dict(r) for h, r in prof.iterrows()},
    )
    (ROOT / "data" / "spread_profile.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(prof.to_string())
    print(f"ticks={len(df)}, failed hour files={failed}")
    print("saved data/spread_profile.json")


if __name__ == "__main__":
    main()

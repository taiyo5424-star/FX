# -*- coding: utf-8 -*-
"""Dukascopy USD/JPY 1分足BIDキャンドル ダウンローダ
URL形式: https://datafeed.dukascopy.com/datafeed/USDJPY/{年}/{月-1:02d}/{日:02d}/BID_candles_min_1.bi5
- 月は0始まり
- bi5 = LZMA圧縮。1レコード24バイト big-endian: [秒オフセット, open, close, low, high](int×5, 価格×1000)+ volume(float)
- 時刻はUTC。JST変換は利用側で行う。
出力: data/usdjpy_m1.parquet
"""
import datetime as dt
import lzma
import struct
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw_bi5"
OUT = ROOT / "data"
RAW.mkdir(parents=True, exist_ok=True)

SYMBOL = "USDJPY"
POINT = 1000.0  # USDJPYは価格×1000で格納
START = dt.date(2023, 1, 1)
END = dt.date(2026, 7, 4)
BASE = "https://datafeed.dukascopy.com/datafeed/{sym}/{y}/{m:02d}/{d:02d}/BID_candles_min_1.bi5"

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0 (research; personal backtest data)"


def fetch_day(day: dt.date):
    """1日分を取得・デコード。戻り値: (day, rows|None) Noneは取得失敗
    注意: UTC当日以降(未完了日)はキャッシュに書かない。ローカルPC(JST)は
    UTCより最大9時間先の日付になるため、未完了日を恒久キャッシュすると
    その日のデータが永久に欠損する(2026-07-20検証で確認した汚染経路)。"""
    cache = RAW / f"{day:%Y-%m-%d}.bi5"
    if cache.exists():
        data = cache.read_bytes()
    else:
        url = BASE.format(sym=SYMBOL, y=day.year, m=day.month - 1, d=day.day)
        data = None
        for attempt in range(4):
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
            return day, None
        if day < dt.datetime.now(dt.timezone.utc).date():   # 完了日のみキャッシュ
            cache.write_bytes(data)
    if not data:
        return day, []
    try:
        raw = lzma.decompress(data)
    except lzma.LZMAError:
        return day, None
    base = dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc)
    rows = []
    for off in range(0, len(raw) - 23, 24):
        t, o, c, lo, hi, v = struct.unpack(">5if", raw[off:off + 24])
        rows.append((base + dt.timedelta(seconds=t),
                     o / POINT, hi / POINT, lo / POINT, c / POINT, v))
    return day, rows


def main():
    days = []
    d = START
    while d <= END:
        if d.weekday() != 5:  # 土曜はデータなし(日曜夜からNY週開始)
            days.append(d)
        d += dt.timedelta(days=1)

    all_rows = []
    failed = []
    empty = []
    done = 0
    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = {ex.submit(fetch_day, day): day for day in days}
        for fut in as_completed(futures):
            day, rows = fut.result()
            done += 1
            if rows is None:
                failed.append(day)
            elif not rows:
                empty.append(day)
            else:
                all_rows.extend(rows)
            if done % 100 == 0:
                print(f"progress {done}/{len(days)} rows={len(all_rows)}", flush=True)

    print(f"downloaded days={len(days)} failed={len(failed)} empty={len(empty)}")
    if failed:
        print("FAILED:", sorted(str(x) for x in failed)[:20])

    df = pd.DataFrame(all_rows, columns=["time_utc", "open", "high", "low", "close", "volume"])
    df = df.sort_values("time_utc").drop_duplicates("time_utc").reset_index(drop=True)
    OUT.mkdir(exist_ok=True)
    df.to_parquet(OUT / "usdjpy_m1.parquet", index=False)
    with open(OUT / "download_report.txt", "w", encoding="utf-8") as f:
        f.write(f"source: Dukascopy datafeed BID candles min1\n")
        f.write(f"period: {START} .. {END} (UTC)\n")
        f.write(f"rows: {len(df)}\n")
        f.write(f"days requested: {len(days)}, failed: {len(failed)}, empty: {len(empty)}\n")
        f.write(f"failed days: {sorted(str(x) for x in failed)}\n")
        f.write(f"empty days: {sorted(str(x) for x in empty)}\n")
        f.write(f"price range: {df['low'].min():.3f} .. {df['high'].max():.3f}\n")
        f.write(f"first: {df['time_utc'].iloc[0]}, last: {df['time_utc'].iloc[-1]}\n")
    print("saved", OUT / "usdjpy_m1.parquet", len(df), "rows")


if __name__ == "__main__":
    main()

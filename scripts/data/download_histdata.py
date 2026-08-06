# -*- coding: utf-8 -*-
"""HistData.com USD/JPY M1 ASCII ダウンローダ
- 過去年: 年次ZIP (/?/ascii/1-minute-bar-quotes/usdjpy/{year})
- 当年  : 月次ZIP (/?/ascii/1-minute-bar-quotes/usdjpy/{year}/{month})
- タイムスタンプは EST固定(UTC-5、夏時間調整なし)→ UTC = EST + 5時間
- 価格はBIDベースのM1バー。出来高列は常に0(HistDataの仕様)。
出力: data/usdjpy_m1.parquet (time_utc, open, high, low, close)
"""
import io
import re
import sys
import time
import zipfile
import datetime as dt
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw_histdata"
OUT = ROOT / "data"
RAW.mkdir(parents=True, exist_ok=True)

PAIR = "usdjpy"
# 過去年は年次ZIP、当年は先月分までの月次ZIPを自動対象
# (HistDataの公表は約1週間遅れのため、月初実行時は先月分が failed に
#  なることがある。その場合は翌週再実行)
_today = dt.datetime.now(dt.timezone.utc).date()   # UTC基準(クラウドとローカルで判定を統一)
YEARS_FULL = list(range(2023, _today.year))
MONTHS_CUR = [(_today.year, m) for m in range(1, 13)
              if dt.date(_today.year, m, 1) < _today.replace(day=1)]

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


def download_zip(year: int, month: int | None) -> bytes | None:
    """1ファイル分のZIPを取得(キャッシュあり)"""
    tag = f"{year}" if month is None else f"{year}{month:02d}"
    cache = RAW / f"DAT_ASCII_USDJPY_M1_{tag}.zip"
    if cache.exists() and cache.stat().st_size > 1000:
        return cache.read_bytes()

    if month is None:
        page_url = f"https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/{PAIR}/{year}"
        datemonth = str(year)
    else:
        page_url = f"https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/{PAIR}/{year}/{month}"
        datemonth = f"{year}{month:02d}"

    for attempt in range(3):
        try:
            r = session.get(page_url, timeout=60)
            r.raise_for_status()
            m = re.search(r'name="tk"\s+value="([^"]+)"', r.text) or \
                re.search(r'id="tk"\s+value="([^"]+)"', r.text)
            if not m:
                print(f"  tk not found for {tag}", flush=True)
                return None
            data = {
                "tk": m.group(1), "date": str(year), "datemonth": datemonth,
                "platform": "ASCII", "timeframe": "M1", "fxpair": "USDJPY",
            }
            r2 = session.post("https://www.histdata.com/get.php", data=data,
                              headers={"Referer": page_url}, timeout=300)
            if r2.status_code == 200 and r2.content[:2] == b"PK":
                cache.write_bytes(r2.content)
                return r2.content
            print(f"  bad response {tag}: status={r2.status_code} bytes={len(r2.content)}", flush=True)
        except Exception as e:
            print(f"  retry {tag}: {type(e).__name__}", flush=True)
        time.sleep(3 * (attempt + 1))
    return None


def parse_zip(blob: bytes) -> pd.DataFrame:
    zf = zipfile.ZipFile(io.BytesIO(blob))
    csv_name = [n for n in zf.namelist() if n.lower().endswith(".csv")][0]
    df = pd.read_csv(
        zf.open(csv_name), sep=";", header=None,
        names=["ts", "open", "high", "low", "close", "vol"],
        dtype={"ts": str},
    )
    # EST固定(UTC-5) → UTC
    t = pd.to_datetime(df["ts"], format="%Y%m%d %H%M%S")
    df["time_utc"] = (t + pd.Timedelta(hours=5)).dt.tz_localize("UTC")
    return df[["time_utc", "open", "high", "low", "close"]]


def main():
    frames = []
    failed = []
    jobs = [(y, None) for y in YEARS_FULL] + MONTHS_CUR
    for year, month in jobs:
        tag = f"{year}" if month is None else f"{year}-{month:02d}"
        print("fetching", tag, flush=True)
        blob = download_zip(year, month)
        if blob is None:
            failed.append(tag)
            continue
        df = parse_zip(blob)
        print(f"  {tag}: {len(df)} rows, {df['time_utc'].min()} .. {df['time_utc'].max()}", flush=True)
        frames.append(df)
        time.sleep(2)  # サーバー負荷への配慮

    if not frames:
        print("FATAL: no data downloaded")
        sys.exit(1)

    df = pd.concat(frames).sort_values("time_utc").drop_duplicates("time_utc").reset_index(drop=True)
    OUT.mkdir(exist_ok=True)
    df.to_parquet(OUT / "usdjpy_m1.parquet", index=False)
    with open(OUT / "download_report.txt", "w", encoding="utf-8") as f:
        f.write("source: HistData.com ASCII M1 (BID base, volume列なし)\n")
        f.write("timezone: original EST(UTC-5 fixed) -> converted to UTC\n")
        f.write(f"rows: {len(df)}\n")
        f.write(f"range: {df['time_utc'].iloc[0]} .. {df['time_utc'].iloc[-1]}\n")
        f.write(f"price range: {df['low'].min():.3f} .. {df['high'].max():.3f}\n")
        f.write(f"failed: {failed}\n")
    print("saved", len(df), "rows; failed:", failed)


if __name__ == "__main__":
    main()

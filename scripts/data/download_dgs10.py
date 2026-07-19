# -*- coding: utf-8 -*-
"""FRED DGS10(米10年国債利回り、日次・NYクローズ)取得
出力: data/dgs10.csv (DATE, DGS10)。APIキー不要のfredgraph.csvを使用。
C010(検証済REJECTED)/C017(2027-01解禁予定)の入力データ。
"""
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"


def main():
    r = requests.get(URL, timeout=60)
    r.raise_for_status()
    out = ROOT / "data" / "dgs10.csv"
    out.write_bytes(r.content)
    df = pd.read_csv(out)
    df.columns = ["day", "dgs10"]
    df["dgs10"] = pd.to_numeric(df["dgs10"], errors="coerce")
    valid = df.dropna()
    print(f"rows={len(df)} valid={len(valid)} range={valid['day'].iloc[0]}..{valid['day'].iloc[-1]} "
          f"last={valid['dgs10'].iloc[-1]}")


if __name__ == "__main__":
    main()

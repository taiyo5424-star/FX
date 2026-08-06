# -*- coding: utf-8 -*-
"""介入サーキットブレーカー検知器
根拠(research/intervention_detector_design.md):
  確定介入日(2024-04-29/05-01/07-11/07-12、2026-04-30/05-01/05-06)は全て
  30分変動150pips超(151〜350pips)。通常日の150pips超は年約5日で、
  それらも急変日(取引停止が正しい日)。
ルール:
  - HALT: 直近24hに30分変動 >= 150pips → 観測時刻から24時間 NO_TRADE
  - WARNING: 直近6hに30分変動 >= 100pips → スプレッド実測必須・新規は要警戒
使い方:
  python3 scripts/ops/intervention_detector.py            # Dukascopyから直近を取得して判定
  python3 scripts/ops/intervention_detector.py --offline  # data/usdjpy_m1_forward.parquetで判定
出力: logs/intervention_status.json(pretrade_checklist S4の入力)
"""
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "data"))

HALT_PIPS = 150.0     # 30分変動、24時間停止
WARN_PIPS = 100.0     # 30分変動、警戒(直近6時間)
PIP = 0.01


def load_recent() -> pd.DataFrame:
    if "--offline" not in sys.argv:
        try:
            from download_dukascopy import fetch_day
            rows = []
            d = dt.datetime.now(dt.timezone.utc).date()   # UTC基準(ローカルTZ非依存)
            for _ in range(4):   # 直近4暦日(週末を跨いでも24h分を確保)
                _, r = fetch_day(d)
                if r:
                    rows.extend(r)
                d -= dt.timedelta(days=1)
            if rows:
                df = pd.DataFrame(rows, columns=["time_utc", "open", "high", "low", "close", "volume"])
                return df.sort_values("time_utc").reset_index(drop=True)
        except Exception as e:
            print(f"オンライン取得失敗({type(e).__name__})→ オフラインにフォールバック")
    p = ROOT / "data" / "usdjpy_m1_forward.parquet"
    if not p.exists():
        sys.exit("データなし: forward_test.pyを先に実行するかオンラインで実行してください")
    return pd.read_parquet(p).sort_values("time_utc").reset_index(drop=True)


def main():
    df = load_recent()
    now = df["time_utc"].iloc[-1]
    df["move30"] = (df["close"] - df["close"].shift(30)).abs() / PIP

    last24 = df[df["time_utc"] >= now - pd.Timedelta(hours=24)]
    last6 = df[df["time_utc"] >= now - pd.Timedelta(hours=6)]
    max24 = float(last24["move30"].max())
    max6 = float(last6["move30"].max())

    status, until, reason = "OK", None, ""
    if max24 >= HALT_PIPS:
        t_hit = last24.loc[last24["move30"].idxmax(), "time_utc"]
        status = "HALT"
        until = str(t_hit + pd.Timedelta(hours=24))
        reason = f"30分変動{max24:.0f}pips(>= {HALT_PIPS})@{t_hit} → 24時間NO_TRADE(介入/急変)"
    elif max6 >= WARN_PIPS:
        status = "WARNING"
        reason = f"直近6hに30分変動{max6:.0f}pips(>= {WARN_PIPS}) → スプレッド実測必須・要警戒"

    out = dict(status=status, checked_at=str(now), data_last_bar=str(now),
               max_move30_pips_24h=round(max24, 1), max_move30_pips_6h=round(max6, 1),
               halt_until=until, reason=reason,
               thresholds=dict(halt=HALT_PIPS, warn=WARN_PIPS))
    p = ROOT / "logs" / "intervention_status.json"
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

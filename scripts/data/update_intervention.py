# -*- coding: utf-8 -*-
"""財務省の公式CSVから介入実施日を取得し historical_events.json を更新する
出典: https://www.mof.go.jp/policy/international_policy/reference/feio/
      foreign_exchange_intervention_operations.csv(平成3年〜最新四半期、日次内訳)
公表は四半期ごと(例: 4-6月期は8月上旬、7-9月期は11月上旬)。
公表前の期間は価格急変検知で暫定登録し、公表後に本スクリプトで確定させる。

使い方:
  python3 scripts/data/update_intervention.py           # 差分があれば更新
  python3 scripts/data/update_intervention.py --check   # 確認のみ(書き換えない)
終了コード: 0=変化なし / 10=更新あり / 1=エラー
"""
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
URL = ("https://www.mof.go.jp/policy/international_policy/reference/feio/"
       "foreign_exchange_intervention_operations.csv")
EVENTS = ROOT / "data" / "calendar" / "historical_events.json"
SINCE = dt.date(2023, 1, 1)   # 価格データの開始以降のみ対象
MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def fetch_official_days() -> list[str]:
    r = requests.get(URL, timeout=90)
    r.raise_for_status()
    df = pd.read_csv(pd.io.common.BytesIO(r.content), encoding="cp932", header=None)
    # 列: 3=西暦年(年初行のみ)/ 4=英語月 / 5=日 / 6=金額(億円)
    year = df[3].where(df[3].astype(str).str.fullmatch(r"\d{4}")).ffill()
    days = []
    for i in range(len(df)):
        mon, day, amt = df.at[i, 4], df.at[i, 5], df.at[i, 6]
        if not isinstance(mon, str) or mon.strip() not in MONTHS:
            continue                      # 「〜期計」など日次行でないものを除外
        try:
            y = int(float(year.iloc[i]))
            d = dt.date(y, MONTHS[mon.strip()], int(float(day)))
            v = float(str(amt).replace(",", ""))
        except (TypeError, ValueError):
            continue
        if v != 0 and d >= SINCE:
            days.append(str(d))
    return sorted(set(days))


def main():
    check_only = "--check" in sys.argv
    ev = json.loads(EVENTS.read_text(encoding="utf-8"))
    current = set(ev.get("intervention", []))
    official = set(fetch_official_days())

    # 公式の最新確定日以降は「暫定登録(価格検知)」なので保持する
    latest_official = max(official) if official else "0000-00-00"
    provisional = {d for d in current if d > latest_official}
    merged = sorted(official | provisional)

    added = sorted(set(merged) - current)
    removed = sorted(current - set(merged))
    print(f"公式確定: {len(official)}日(最新 {latest_official}) / "
          f"暫定保持: {len(provisional)}日 / 追加 {len(added)} / 削除 {len(removed)}")
    if added:
        print("  + " + ", ".join(added))
    if removed:
        print("  - " + ", ".join(removed) + "  ← 公式で介入なしと確定(保守除外の解除)")

    if not (added or removed):
        print("変化なし")
        return 0
    if check_only:
        print("--check のため書き換えなし")
        return 10

    ev["intervention"] = merged
    note = (f"{dt.date.today()}: 財務省公式CSVで自動更新(確定{len(official)}日"
            f"+暫定{len(provisional)}日)。出典 {URL}")
    ev.setdefault("_notes", []).insert(0, note)
    EVENTS.write_text(json.dumps(ev, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"更新: {EVENTS}")
    return 10


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        sys.exit(1)

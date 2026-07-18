# -*- coding: utf-8 -*-
"""第3陣候補戦略(C018 イベント後ドリフト / C019 日次時系列モメンタム)
事前登録: strategies/candidates/batch_003_prereg.md(実行前確定・変更禁止)
シグナルは確定情報のみ使用。エントリーは常にシグナル確定後の次バー始値。
"""
import datetime as dt

import numpy as np
import pandas as pd

from engine import PIP
from strategies_batch1 import JST_9H, build_daily


def us_dst(d: dt.date) -> bool:
    """米夏時間(3月第2日曜〜11月第1日曜)。日付単位の近似。"""
    def nth_sunday(y, m, n):
        x = dt.date(y, m, 1)
        first_sun = x + dt.timedelta(days=(6 - x.weekday()) % 7)
        return first_sun + dt.timedelta(days=7 * (n - 1))
    return nth_sunday(d.year, 3, 2) <= d < nth_sunday(d.year, 11, 1)


def release_time_utc(date_str: str, ev_type: str) -> pd.Timestamp:
    d = dt.date.fromisoformat(date_str)
    if ev_type in ("cpi", "nfp"):
        hh = 12 if us_dst(d) else 13
        return pd.Timestamp(f"{date_str} {hh}:30", tz="UTC")
    if ev_type == "fomc":
        hh = 18 if us_dst(d) else 19
        return pd.Timestamp(f"{date_str} {hh}:00", tz="UTC")
    raise ValueError(ev_type)


# ---------- C018: 米指標イベント後ドリフト ----------
def c018_entries(df, events: dict, intervention_mask=None,
                 k_min=15, thr_pips=10.0, sl_pips=12.0, hold_hours=4,
                 tp_mult=None):
    """発表T0直前終値→T0+K分終値の変動が閾値以上なら初動方向へ追随。
    - 基準バー: open_time <= T0-2分 の最終バー(終値がT0-1分までに確定)
    - 判定バー: open_time <= T0+K-1分 の最終バー
    - エントリー: 判定バーの次バー始値(ギャップ30分超なら見送り)
    - intervention_mask: Trueのバーはエントリー禁止(Noneなら制限なし)
    """
    t = df["time_utc"].values
    c = df["close"].values
    n = len(df)
    entries = []
    for ev_type in ("cpi", "nfp", "fomc"):
        for ds in events.get(ev_type, []):
            t0 = release_time_utc(ds, ev_type)
            ref_i = int(np.searchsorted(t, (t0 - pd.Timedelta(minutes=1)).to_datetime64())) - 1
            post_i = int(np.searchsorted(t, (t0 + pd.Timedelta(minutes=k_min)).to_datetime64())) - 1
            if ref_i < 0 or post_i <= ref_i or post_i + 1 >= n:
                continue
            # 発表直前10分以内にデータがあること(休場・欠損の除外)
            if pd.Timestamp(t[ref_i], tz="UTC") < t0 - pd.Timedelta(minutes=10):
                continue
            move = (c[post_i] - c[ref_i]) / PIP
            if abs(move) < thr_pips:
                continue
            ei = post_i + 1
            if pd.Timestamp(t[ei], tz="UTC") > t0 + pd.Timedelta(minutes=k_min + 30):
                continue  # データギャップ
            if intervention_mask is not None and intervention_mask[ei]:
                continue
            end_t = t0 + pd.Timedelta(hours=k_min / 60 + hold_hours)
            j = int(np.searchsorted(t, end_t.to_datetime64())) - 1
            if j <= ei:
                continue
            entries.append(dict(
                entry_idx=ei, dir=int(np.sign(move)), sl_pips=float(sl_pips),
                tp_pips=float(tp_mult * sl_pips) if tp_mult else None,
                max_exit_idx=j, meta_day=ds, meta_event=ev_type,
                meta_move=round(float(move), 1)))
    entries.sort(key=lambda e: e["entry_idx"])
    return entries


# ---------- C019: 日次時系列モメンタム(反転日のみ新規) ----------
def c019_entries(df, event_mask, daily=None, lookback=20, sl_atr=1.5,
                 hold_days=5, strength_f=0.0):
    """日足終値のL日リターン符号が前日から反転した日の翌営業日、
    東京9:00以降最初のバーで符号方向へエントリー。時間決済(hold_days)。"""
    if daily is None:
        daily = build_daily(df)
    jm = df["jst_min"].values
    d = daily.reset_index(names="day")
    close = d["close"].values
    atr = d["atr14"].values
    entries = []
    for i in range(max(lookback + 1, 21), len(d) - 1):
        if np.isnan(atr[i]) or atr[i] <= 0:
            continue
        r_now = close[i] - close[i - lookback]
        r_prev = close[i - 1] - close[i - 1 - lookback]
        s_now, s_prev = np.sign(r_now), np.sign(r_prev)
        if s_now == 0 or s_now == s_prev:
            continue
        if strength_f > 0 and abs(r_now) < strength_f * atr[i]:
            continue
        nxt = d.iloc[i + 1]
        s, e = int(nxt["first_idx"]), int(nxt["last_idx"])
        cand = np.arange(s, e + 1)[jm[s:e + 1] >= JST_9H]
        if len(cand) == 0:
            continue
        ei = int(cand[0])
        if event_mask[ei]:
            continue
        j_end = min(i + 1 + hold_days, len(d) - 1)
        atr_pips = atr[i] / PIP
        entries.append(dict(
            entry_idx=ei, dir=int(s_now),
            sl_pips=float(np.clip(sl_atr * atr_pips, 20, 80)), tp_pips=None,
            max_exit_idx=int(d.iloc[j_end]["last_idx"]),
            meta_day=str(d.iloc[i]["day"]), meta_atr=round(atr_pips, 1)))
    return entries


# ---------- スワップ算入(C019用、事前登録値) ----------
def apply_swap(trades: pd.DataFrame, long_pips_per_day=0.75,
               short_pips_per_day=-2.0) -> pd.DataFrame:
    """保有日数(ロールオーバー回数近似)に応じてR
    を調整。事前登録: 受取は半分ヘアカット、支払いは3割増しの保守値。"""
    if len(trades) == 0:
        return trades
    tr = trades.copy()
    days = ((tr["exit_time"] - tr["entry_time"]).dt.total_seconds() / 86400).round().astype(int)
    swap_pips = np.where(tr["dir"] > 0, long_pips_per_day * days, short_pips_per_day * days)
    tr["R"] = tr["R"] + swap_pips / tr["sl_pips"]
    tr["pips_net"] = tr["pips_net"] + swap_pips
    return tr

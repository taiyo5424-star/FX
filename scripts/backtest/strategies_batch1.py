# -*- coding: utf-8 -*-
"""第1陣候補戦略のシグナル生成(C001 / C003 / C009)
各関数は entries(list[dict]) を返す。engine.simulate() に渡す形式:
  dict(entry_idx, dir, sl_pips, tp_pips|None, max_exit_idx, meta_*)
シグナルは確定情報のみ使用。エントリーは常にシグナル確定後の次バー始値。
"""
import datetime as dt

import jpholiday
import numpy as np
import pandas as pd

from engine import PIP, eu_dst

JST_9H = 540    # 9:00
JST_955 = 595   # 9:55
JST_15H = 900   # 15:00
JST_23H = 1380  # 23:00


def day_index(df: pd.DataFrame) -> dict:
    """jst_date -> (start_idx, end_idx_inclusive)"""
    g = df.groupby("jst_date").indices
    return {d: (int(v[0]), int(v[-1])) for d, v in g.items()}


def is_jp_business_day(d: dt.date) -> bool:
    return d.weekday() < 5 and not jpholiday.is_holiday(d)


def gotobi_settlement_days(dates: set) -> set:
    """5・10日(ゴトー日)の実質決済日(前営業日繰り上げ)を返す"""
    months = sorted({(d.year, d.month) for d in dates})
    result = set()
    for y, m in months:
        for g in (5, 10, 15, 20, 25, 30):
            try:
                d = dt.date(y, m, g)
            except ValueError:
                continue
            guard = 0
            while not is_jp_business_day(d) and guard < 7:
                d -= dt.timedelta(days=1)
                guard += 1
            if d in dates:
                result.add(d)
    return result


# ---------- C001: ゴトー日仲値ドル買い ----------
def c001_entries(df, event_mask, entry_jst_min=540, sl_pips=15, tp_pips=None):
    didx = day_index(df)
    gotobi = gotobi_settlement_days(set(didx.keys()))
    jm = df["jst_min"].values
    entries = []
    for d in sorted(gotobi):
        s, e = didx[d]
        seg = np.arange(s, e + 1)
        in_win = seg[(jm[s:e + 1] >= entry_jst_min) & (jm[s:e + 1] < JST_955)]
        if len(in_win) < 20:      # データ薄い日はスキップ
            continue
        ei = int(in_win[0])
        if event_mask[ei]:
            continue
        exit_candidates = seg[jm[s:e + 1] < JST_955]
        entries.append(dict(entry_idx=ei, dir=+1, sl_pips=float(sl_pips),
                            tp_pips=float(tp_pips) if tp_pips else None,
                            max_exit_idx=int(exit_candidates[-1]),
                            meta_day=str(d)))
    return entries


# ---------- C003: 東京レンジ→ロンドン初動ブレイク ----------
def c003_entries(df, event_mask, buffer_pips=3, sl_mode="range_mid", fixed_sl=20,
                 tp_mode="range", tp_k=0.7, min_range=15, max_range=80):
    didx = day_index(df)
    jm = df["jst_min"].values
    um = df["utc_min"].values
    h, lo = df["high"].values, df["low"].values
    entries = []
    for d in sorted(didx.keys()):
        if d.weekday() >= 5:
            continue
        s, e = didx[d]
        seg = np.arange(s, e + 1)
        tokyo = seg[(jm[s:e + 1] >= JST_9H) & (jm[s:e + 1] < JST_15H)]
        if len(tokyo) < 200:
            continue
        r_hi = h[tokyo].max()
        r_lo = lo[tokyo].min()
        rng = (r_hi - r_lo) / PIP
        if not (min_range <= rng <= max_range):
            continue
        # ロンドン窓: 夏 7:00-10:00 UTC / 冬 8:00-11:00 UTC
        ws = 7 * 60 if eu_dst(d) else 8 * 60
        lon = seg[(um[s:e + 1] >= ws) & (um[s:e + 1] < ws + 180)]
        if len(lon) < 30:
            continue
        up = h[lon] > r_hi + buffer_pips * PIP
        dn = lo[lon] < r_lo - buffer_pips * PIP
        first_up = int(np.argmax(up)) if up.any() else 10 ** 9
        first_dn = int(np.argmax(dn)) if dn.any() else 10 ** 9
        if first_up == first_dn:  # 双方なし or 同一バー両抜け(乱高下)→見送り
            continue
        k = min(first_up, first_dn)
        direction = +1 if first_up < first_dn else -1
        sig_idx = int(lon[k])
        ei = sig_idx + 1                     # 次バー始値でエントリー
        if ei > e or event_mask[ei]:
            continue
        sl = rng / 2 + buffer_pips if sl_mode == "range_mid" else float(fixed_sl)
        sl = float(min(max(sl, 8.0), 40.0))  # 過小・過大SLを制限
        tp = float(tp_k * rng) if tp_mode == "range" else None
        exit_c = seg[jm[s:e + 1] < JST_23H]
        entries.append(dict(entry_idx=ei, dir=direction, sl_pips=sl, tp_pips=tp,
                            max_exit_idx=int(exit_c[-1]), meta_day=str(d),
                            meta_range=round(rng, 1)))
    return entries


# ---------- C009: 日足5本線押し目(上位トレンド一致) ----------
def build_daily(df) -> pd.DataFrame:
    """NYクローズ近似(UTC+2hシフト)で日足を構築"""
    key = (df["time_utc"] + pd.Timedelta(hours=2)).dt.date
    g = df.groupby(key)
    daily = pd.DataFrame({
        "open": g["open"].first(), "high": g["high"].max(),
        "low": g["low"].min(), "close": g["close"].last(),
        "first_idx": g.apply(lambda x: x.index[0], include_groups=False),
        "last_idx": g.apply(lambda x: x.index[-1], include_groups=False),
    })
    daily = daily[daily.index.map(lambda d: d.weekday() < 5)]
    daily["ma5"] = daily["close"].rolling(5).mean()
    daily["ma20"] = daily["close"].rolling(20).mean()
    tr = np.maximum(daily["high"] - daily["low"],
                    np.maximum((daily["high"] - daily["close"].shift(1)).abs(),
                               (daily["low"] - daily["close"].shift(1)).abs()))
    daily["atr14"] = tr.rolling(14).mean()
    return daily


def c009_entries(df, event_mask, daily=None, sl_atr=1.2, tp_atr=2.0,
                 require_close_above=True, timeout_days=10, allow_short=True):
    if daily is None:
        daily = build_daily(df)
    jm = df["jst_min"].values
    entries = []
    d = daily.reset_index(names="day")
    for i in range(21, len(d) - 1):
        row, prev = d.iloc[i], d.iloc[i - 1]
        if np.isnan(row["ma20"]) or np.isnan(row["atr14"]) or row["atr14"] <= 0:
            continue
        atr_pips = row["atr14"] / PIP
        long_sig = (row["close"] > row["ma20"] and row["ma20"] > d["ma20"].iloc[i - 5]
                    and row["low"] <= row["ma5"] and prev["close"] > prev["ma5"]
                    and (not require_close_above or row["close"] > row["ma5"]))
        short_sig = (allow_short and row["close"] < row["ma20"] and row["ma20"] < d["ma20"].iloc[i - 5]
                     and row["high"] >= row["ma5"] and prev["close"] < prev["ma5"]
                     and (not require_close_above or row["close"] < row["ma5"]))
        if not (long_sig or short_sig):
            continue
        direction = +1 if long_sig else -1
        # 翌営業日の東京9:00 JST以降の最初のバーでエントリー(コアタイム内)
        nxt = d.iloc[i + 1]
        s, e = int(nxt["first_idx"]), int(nxt["last_idx"])
        cand = np.arange(s, e + 1)[jm[s:e + 1] >= JST_9H]
        if len(cand) == 0:
            continue
        ei = int(cand[0])
        if event_mask[ei]:
            continue
        j_end = min(i + 1 + timeout_days, len(d) - 1)
        entries.append(dict(entry_idx=ei, dir=direction,
                            sl_pips=float(np.clip(sl_atr * atr_pips, 15, 45)),
                            tp_pips=float(np.clip(tp_atr * atr_pips, 20, 90)),
                            max_exit_idx=int(d.iloc[j_end]["last_idx"]),
                            meta_day=str(row["day"]), meta_atr=round(atr_pips, 1)))
    return entries

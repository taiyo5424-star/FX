# -*- coding: utf-8 -*-
"""第2陣候補戦略(C009v2 / C005)
データ衛生: C009v2のゲート設計・選択はIS期間(〜2025-06)のみで行うこと
(選択ロジックはrunner側でIS成績のみ使用。本ファイルはシグナル生成のみ)。
"""
import numpy as np
import pandas as pd

from engine import PIP
from strategies_batch1 import JST_9H, build_daily, c009_entries as _c009_base

JST_23H = 1380
CORE_UTC_MIN_END = 18 * 60   # コアタイム JST9:00〜翌3:00 = UTC 0:00〜18:00


# ---------- C009v2: レジームゲート付き押し目 ----------
def build_daily_v2(df) -> pd.DataFrame:
    """v1のdailyにゲート指標(ADX14 / 正規化MA20傾き / 効率比10)を追加"""
    daily = build_daily(df)
    h, l, c = daily["high"], daily["low"], daily["close"]
    # Wilder ADX(14)
    up = h.diff()
    dn = -l.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum(h - l, np.maximum((h - c.shift(1)).abs(), (l - c.shift(1)).abs()))
    alpha = 1 / 14
    atr_w = tr.ewm(alpha=alpha, adjust=False).mean()
    pdi = 100 * pd.Series(plus_dm, index=daily.index).ewm(alpha=alpha, adjust=False).mean() / atr_w
    mdi = 100 * pd.Series(minus_dm, index=daily.index).ewm(alpha=alpha, adjust=False).mean() / atr_w
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    daily["adx14"] = dx.ewm(alpha=alpha, adjust=False).mean()
    # 正規化MA20傾き: |MA20[t]-MA20[t-5]| / ATR14
    daily["slope_norm"] = (daily["ma20"] - daily["ma20"].shift(5)).abs() / daily["atr14"]
    # Kaufman効率比(10日)
    daily["er10"] = (c - c.shift(10)).abs() / c.diff().abs().rolling(10).sum()
    return daily


def c009v2_entries(df, event_mask, daily=None, sl_atr=1.0, tp_atr=2.5,
                   gate_type="adx", gate_thr=25.0, require_close_above=True):
    """v1シグナル + シグナル日のゲート指標が閾値以上の場合のみ採用"""
    if daily is None:
        daily = build_daily_v2(df)
    base = _c009_base(df, event_mask, daily=daily, sl_atr=sl_atr, tp_atr=tp_atr,
                      require_close_above=require_close_above)
    col = {"adx": "adx14", "slope": "slope_norm", "er": "er10"}[gate_type]
    gate = daily[col]
    day_of = {str(d): v for d, v in gate.items()}
    out = []
    for e in base:
        v = day_of.get(e["meta_day"])
        if v is not None and not np.isnan(v) and v >= gate_thr:
            out.append(e)
    return out


# ---------- C005: 前日NY高安の初回タッチ反発 ----------
def c005_entries(df, event_mask, daily=None, sl_pips=15, tp_mult=1.2,
                 trend_filter=True, level_buffer=0.0):
    """前日(NYクローズ日)高値・安値への当日初回タッチで逆張り。
    - 高値タッチ→ショート / 安値タッチ→ロング
    - 初回タッチのみ(同日2回目以降は無効=ブレイクしやすい)
    - コアタイム内(UTC 0:00-18:00)のみエントリー
    - trend_filter: 前日レンジ<=1.5×ATR14(強トレンド日の翌日はフェードしない)
    - 時間決済: 当日NY日終端"""
    if daily is None:
        daily = build_daily(df)
    h, lo = df["high"].values, df["low"].values
    um = df["utc_min"].values
    d = daily.reset_index(names="day")
    entries = []
    for i in range(15, len(d)):
        prev, cur = d.iloc[i - 1], d.iloc[i]
        if np.isnan(prev["atr14"]) or prev["atr14"] <= 0:
            continue
        if trend_filter and (prev["high"] - prev["low"]) > 1.5 * prev["atr14"]:
            continue
        ph = prev["high"] + level_buffer * PIP
        pl = prev["low"] - level_buffer * PIP
        s, e = int(cur["first_idx"]), int(cur["last_idx"])
        hi_seg, lo_seg = h[s:e + 1], lo[s:e + 1]
        touched_hi = touched_lo = False
        for k in range(e - s + 1):
            gi = s + k
            hit_hi = hi_seg[k] >= ph
            hit_lo = lo_seg[k] <= pl
            if hit_hi and not touched_hi:
                touched_hi = True
                if (not hit_lo) and 0 <= um[gi] < CORE_UTC_MIN_END and gi + 1 <= e \
                        and not event_mask[gi + 1]:
                    entries.append(dict(entry_idx=gi + 1, dir=-1, sl_pips=float(sl_pips),
                                        tp_pips=float(tp_mult * sl_pips), max_exit_idx=e,
                                        meta_day=str(cur["day"]), meta_side="fade_high"))
            if hit_lo and not touched_lo:
                touched_lo = True
                if (not hit_hi) and 0 <= um[gi] < CORE_UTC_MIN_END and gi + 1 <= e \
                        and not event_mask[gi + 1]:
                    entries.append(dict(entry_idx=gi + 1, dir=+1, sl_pips=float(sl_pips),
                                        tp_pips=float(tp_mult * sl_pips), max_exit_idx=e,
                                        meta_day=str(cur["day"]), meta_side="fade_low"))
            if touched_hi and touched_lo:
                break
    return entries

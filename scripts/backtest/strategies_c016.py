# -*- coding: utf-8 -*-
"""C016: 東京レンジ拡大日のトレンド継続(C015研究から導出、IS限定開発)
仮説: 東京時間(9-15時JST)のレンジが直近20日平均の一定倍以上に拡大した日は
情報フロー主導のトレンド日である確率が高く(IS実測: 基礎11.4%→28.4%)、
15時時点の方向へ午後〜NYで続伸しやすい。
シグナル(15:00 JST確定): tokyo_range_ratio >= thr かつ 15時終値が東京レンジ端20%
エントリー: 15:00 JST直後 または ロンドンオープン直後の次バー始値(方向=東京方向)
"""
import numpy as np

from engine import PIP, eu_dst
from strategies_batch1 import JST_9H, JST_15H, day_index

JST_23H = 1380
JST_25H = 60  # 翌1:00 JST(NY午後) = jst_min 60 ※日跨ぎのため当日セグメントでは扱わない


def c016_entries(df, event_mask, ratio_thr=1.3, entry_mode="tokyo_close",
                 sl_mode="half_range", fixed_sl=20, exit_jst_min=JST_23H,
                 require_edge_close=True):
    didx = day_index(df)
    jm = df["jst_min"].values
    um = df["utc_min"].values
    h, lo = df["high"].values, df["low"].values
    o, c = df["open"].values, df["close"].values

    days = sorted(d for d in didx.keys() if d.weekday() < 5)
    tokyo_ranges = {}   # 20日平均計算用(当日を含まない過去平均にする)
    hist = []
    entries = []
    for d in days:
        s, e = didx[d]
        seg = np.arange(s, e + 1)
        tokyo = seg[(jm[s:e + 1] >= JST_9H) & (jm[s:e + 1] < JST_15H)]
        if len(tokyo) < 200:
            continue
        t_hi = h[tokyo].max()
        t_lo = lo[tokyo].min()
        rng = (t_hi - t_lo) / PIP
        avg20 = np.mean(hist[-20:]) if len(hist) >= 20 else None
        hist.append(rng)          # 過去平均は当日を含まない(ルックアヘッド防止)
        if avg20 is None or avg20 <= 0:
            continue
        ratio = rng / avg20
        if ratio < ratio_thr:
            continue
        t_open = o[tokyo[0]]
        t_close = c[tokyo[-1]]
        direction = 1 if t_close > t_open else -1
        pos = (t_close - t_lo) / max(t_hi - t_lo, 1e-9)
        if require_edge_close and not (pos >= 0.8 or pos <= 0.2):
            continue
        if require_edge_close and ((direction > 0) != (pos >= 0.8)):
            continue  # 方向と引け位置の不一致は見送り

        if entry_mode == "tokyo_close":
            cand = seg[jm[s:e + 1] >= JST_15H]
        else:  # london_open
            # 重要: JST日のバー列は0:00始まりのため、単純な um>=ws は
            # 東京セッションより前の深夜バーを拾う(ルックアヘッド)。
            # 必ず「15:00 JST以降 かつ ロンドン開場以降」で選ぶ。
            ws = (7 if eu_dst(d) else 8) * 60
            cand = seg[(jm[s:e + 1] >= JST_15H) & (um[s:e + 1] >= ws)]
        if len(cand) == 0:
            continue
        ei = int(cand[0])
        if event_mask[ei] or ei > e:
            continue
        sl = rng / 2 if sl_mode == "half_range" else float(fixed_sl)
        sl = float(min(max(sl, 10.0), 40.0))
        exit_c = seg[jm[s:e + 1] < exit_jst_min]
        if len(exit_c) == 0:
            continue
        entries.append(dict(entry_idx=ei, dir=direction, sl_pips=sl, tp_pips=None,
                            max_exit_idx=int(exit_c[-1]), meta_day=str(d),
                            meta_ratio=round(ratio, 2)))
    return entries

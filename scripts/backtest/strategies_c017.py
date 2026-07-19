# -*- coding: utf-8 -*-
"""C017: 金利残差モメンタム(C010の符号反転ファミリー)
仮説: 米金利で説明できないUSD/JPYの残差変動は、介入・政策期待・フローなど
金利外の情報の反映であり、翌日も同方向に継続しやすい(収斂ではなく持続)。

**検証解禁条件(priority_queue M6 / docs/04多重検定規律)**:
  C010検証(2026-07-08)と同一データでの検証はpハッキングのため禁止。
  2026-07-01以降の新データのみを判定対象(真のOOS)とし、
  それが6ヶ月分溜まる2027-01-05以降に runner_c017.py で検証する。
  それまで本ファイルは実装準備のみ(実行はランナーのゲートが拒否する)。
"""
import numpy as np

from engine import PIP
from strategies_batch1 import JST_9H
from strategies_c010 import build_joint_daily  # 残差z計算は同一(再利用)


def c017_entries(df, event_mask, joint=None, z_thr=1.5, sl_atr=1.2, tp_atr=1.5,
                 timeout_days=3, min_corr=0.3):
    """C010と同じシグナル量zを使用し、方向のみ反転(残差方向へ追随)"""
    if joint is None:
        joint = build_joint_daily(df)
    jm = df["jst_min"].values
    entries = []
    j = joint
    for i in range(len(j) - 1):
        row = j.iloc[i]
        if any(np.isnan(row[k]) for k in ("z", "beta", "corr60", "atr14")):
            continue
        if row["corr60"] < min_corr or row["atr14"] <= 0:
            continue
        if abs(row["z"]) < z_thr:
            continue
        direction = +1 if row["z"] > 0 else -1   # ← C010との唯一の差(追随)
        nxt = j.iloc[i + 1]
        if (nxt["day"] - row["day"]).days > 3:
            continue
        s, e = int(nxt["first_idx"]), int(nxt["last_idx"])
        cand = np.arange(s, e + 1)[jm[s:e + 1] >= JST_9H]
        if len(cand) == 0:
            continue
        ei = int(cand[0])
        if event_mask[ei]:
            continue
        atr_pips = row["atr14"] / PIP
        j_end = min(i + 1 + timeout_days, len(j) - 1)
        entries.append(dict(entry_idx=ei, dir=direction,
                            sl_pips=float(np.clip(sl_atr * atr_pips, 15, 45)),
                            tp_pips=float(np.clip(tp_atr * atr_pips, 15, 60)),
                            max_exit_idx=int(j.iloc[j_end]["last_idx"]),
                            meta_day=str(row["day"]), meta_z=round(float(row["z"]), 2)))
    return entries

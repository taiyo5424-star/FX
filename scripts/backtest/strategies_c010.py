# -*- coding: utf-8 -*-
"""C010: 米10年金利との短期乖離収斂
仮説: USD/JPYの日次変動は米10年金利変動と強い正相関を持つ。金利で説明できない
一時的な乖離(残差のzスコアが極端)は数日内に収斂しやすい。
シグナル(NY日t終値で確定、DGS10も同じNYクローズ値):
  過去60日ローリング回帰 ΔUSDJPY_pips = beta×ΔDGS10_bp の残差e_t、
  z = e_t / std20(e)。z >= thr → 割高 → 翌東京9:00ショート(z <= -thr はロング)
エントリー: 翌NY営業日の東京9:00 JST以降最初のバー始値(シグナル確定の約11時間後)
イグジット: ATRベースSL/TP + 固定日数タイムアウト
ルックアヘッド注意: 回帰・zはt日以前のデータのみ。エントリーはt+1日。
"""
import numpy as np
import pandas as pd
from pathlib import Path

from engine import PIP
from strategies_batch1 import JST_9H, build_daily

ROOT = Path(__file__).resolve().parents[2]


def build_joint_daily(df) -> pd.DataFrame:
    """日足(NYクローズ近似)とDGS10を同一日付で結合し、残差zを計算"""
    daily = build_daily(df).reset_index(names="day")
    rates = pd.read_csv(ROOT / "data" / "dgs10.csv")
    rates.columns = ["day", "dgs10"]
    rates["day"] = pd.to_datetime(rates["day"]).dt.date
    rates["dgs10"] = pd.to_numeric(rates["dgs10"], errors="coerce")
    j = daily.merge(rates, on="day", how="inner").dropna(subset=["dgs10", "atr14"])
    j["d_fx"] = j["close"].diff() / PIP          # pips
    j["d_rate"] = j["dgs10"].diff() * 100        # bp
    # ローリング回帰(60日、切片なし): beta = Σxy/Σxx。当日を含む=シグナルは当日終値確定後
    W = 60
    xy = (j["d_fx"] * j["d_rate"]).rolling(W).sum()
    xx = (j["d_rate"] ** 2).rolling(W).sum()
    j["beta"] = xy / xx.replace(0, np.nan)
    j["resid"] = j["d_fx"] - j["beta"] * j["d_rate"]
    j["z"] = j["resid"] / j["resid"].rolling(20).std().replace(0, np.nan)
    j["corr60"] = j["d_fx"].rolling(W).corr(j["d_rate"])
    return j


def c010_entries(df, event_mask, joint=None, z_thr=1.5, sl_atr=1.2, tp_atr=1.2,
                 timeout_days=3, min_corr=0.3):
    """min_corr: 相関レジームが崩れている期間(介入期・リスクオフ)は取引しない"""
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
        direction = -1 if row["z"] > 0 else +1   # 割高→ショート / 割安→ロング
        nxt = j.iloc[i + 1]
        # 翌NY日が暦上の翌営業日でない(休場明け等)場合は見送り
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
        # タイムアウト: timeout_days後のNY日終端
        j_end = min(i + 1 + timeout_days, len(j) - 1)
        entries.append(dict(entry_idx=ei, dir=direction,
                            sl_pips=float(np.clip(sl_atr * atr_pips, 15, 45)),
                            tp_pips=float(np.clip(tp_atr * atr_pips, 15, 60)),
                            max_exit_idx=int(j.iloc[j_end]["last_idx"]),
                            meta_day=str(row["day"]), meta_z=round(float(row["z"]), 2)))
    return entries

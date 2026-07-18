# -*- coding: utf-8 -*-
"""バックテストエンジン(docs/04準拠)
設計原則:
  - シグナルは確定バーの情報のみ使用(エントリーは翌バー始値)
  - 同一バー内でSLとTPの両方に到達しうる場合はSL優先(最悪ケース)
  - コスト: 往復スプレッド+スリッページをpipsで控除、AIコスト配賦はR単位で控除
  - データはBIDベースM1(UTC)。JST = UTC+9
"""
import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PIP = 0.01  # USD/JPY 1pip = 0.01円


# ---------- コストモデル ----------
@dataclass
class CostModel:
    spread_pips: float = 0.4      # 保守値(松井公表0.2銭の2倍)
    slip_pips: float = 0.3        # 片道スリッページ想定
    ai_cost_R: float = 0.04       # AIコスト配賦(R)。研究費確定後に更新
    entry_delay_bars: int = 0     # ストレステスト用(約定遅延)

    @property
    def round_trip_pips(self) -> float:
        return self.spread_pips + 2 * self.slip_pips


STRESS = dict(spread_pips=0.8, slip_pips=0.9, ai_cost_R=0.06, entry_delay_bars=1)


# ---------- データ ----------
def load_data() -> pd.DataFrame:
    df = pd.read_parquet(ROOT / "data" / "usdjpy_m1.parquet")
    df = df.sort_values("time_utc").reset_index(drop=True)
    t = df["time_utc"]
    df["utc_min"] = (t.dt.hour * 60 + t.dt.minute).astype(np.int32)
    jst = t + pd.Timedelta(hours=9)
    df["jst_date"] = jst.dt.date
    df["jst_min"] = (jst.dt.hour * 60 + jst.dt.minute).astype(np.int32)
    return df


def eu_dst(d: dt.date) -> bool:
    """EU夏時間(3月最終日曜1:00UTC〜10月最終日曜1:00UTC)。日付単位の近似。"""
    def last_sunday(y, m):
        x = dt.date(y, m, 31)
        return x - dt.timedelta(days=(x.weekday() + 1) % 7)
    return last_sunday(d.year, 3) <= d < last_sunday(d.year, 10)


# ---------- イベント除外 ----------
def load_event_windows() -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """data/calendar/historical_events.json から除外ウィンドウ(UTC)を構築"""
    p = ROOT / "data" / "calendar" / "historical_events.json"
    if not p.exists():
        raise FileNotFoundError("historical_events.json がありません。イベントフィルタなしの検証は無効です(docs/04)")
    ev = json.loads(p.read_text(encoding="utf-8"))
    win = []

    def add(date_str, time_utc_str, pad_min):
        t = pd.Timestamp(f"{date_str} {time_utc_str}", tz="UTC")
        win.append((t - pd.Timedelta(minutes=pad_min), t + pd.Timedelta(minutes=pad_min)))

    for d in ev.get("fomc", []):
        add(d, "18:30", 120)          # 声明18:00/19:00UTC(夏/冬)+会見 → 中間値±2hで両方覆う
    for d in ev.get("boj", []):
        # 日銀は発表時刻不定(正午前後JST)→ JST 10:30-16:00 を除外(UTC 1:30-7:00)
        t0 = pd.Timestamp(f"{d} 01:30", tz="UTC")
        win.append((t0, t0 + pd.Timedelta(hours=5.5)))
    for d in ev.get("nfp", []):
        add(d, "13:00", 45)           # 12:30/13:30UTC(夏/冬)を±45分で両方覆う
    for d in ev.get("cpi", []):
        add(d, "13:00", 45)
    for d in ev.get("intervention", []):
        t0 = pd.Timestamp(f"{d} 00:00", tz="UTC")
        win.append((t0, t0 + pd.Timedelta(hours=48)))  # 介入日+翌日(最低24時間ルールを保守拡大)
    return win


def make_event_mask(df: pd.DataFrame, windows) -> np.ndarray:
    """バーごとの「イベント除外中」フラグ"""
    mask = np.zeros(len(df), dtype=bool)
    t = df["time_utc"].values
    for s, e in windows:
        mask |= (t >= s.to_datetime64()) & (t <= e.to_datetime64())
    return mask


# ---------- 約定シミュレーション ----------
def simulate(df: pd.DataFrame, entries: list[dict], cost: CostModel) -> pd.DataFrame:
    """entries: dict(entry_idx, dir(+1/-1), sl_pips, tp_pips|None, max_exit_idx)
    entry_idx時点の始値でエントリー(entry_delay_bars分後ろ倒し)。
    戻り値: 取引一覧(R確定済み)"""
    o = df["open"].values
    h = df["high"].values
    lo = df["low"].values
    c = df["close"].values
    n = len(df)
    out = []
    for e in entries:
        i = e["entry_idx"] + cost.entry_delay_bars
        if i >= n:
            continue
        j_max = min(e["max_exit_idx"], n - 1)
        if i > j_max:
            continue
        d = e["dir"]
        ep = o[i]
        sl_pips = e["sl_pips"]
        sl_price = ep - d * sl_pips * PIP
        tp_price = ep + d * e["tp_pips"] * PIP if e.get("tp_pips") else None
        exit_price, exit_idx, reason = None, None, None
        if i <= j_max:
            hs, ls = h[i:j_max + 1], lo[i:j_max + 1]
            if d > 0:
                sl_hit = ls <= sl_price
                tp_hit = hs >= tp_price if tp_price else np.zeros_like(sl_hit)
            else:
                sl_hit = hs >= sl_price
                tp_hit = ls <= tp_price if tp_price else np.zeros_like(sl_hit)
            either = sl_hit | tp_hit
            if either.any():
                k = int(np.argmax(either))
                exit_idx = i + k
                if sl_hit[k]:                       # SL優先(最悪ケース)
                    exit_price, reason = sl_price, "SL"
                else:
                    exit_price, reason = tp_price, "TP"
        if exit_price is None:
            exit_idx = j_max
            exit_price, reason = c[j_max], "TIME"
        pips = d * (exit_price - ep) / PIP - cost.round_trip_pips
        r = pips / sl_pips - cost.ai_cost_R
        out.append(dict(
            entry_time=df["time_utc"].iloc[i], exit_time=df["time_utc"].iloc[exit_idx],
            dir=d, entry=ep, exit=exit_price, reason=reason,
            pips_net=pips, R=r, sl_pips=sl_pips, **{k: v for k, v in e.items() if k.startswith("meta_")},
        ))
    return pd.DataFrame(out)


# ---------- 評価指標 ----------
def metrics(trades: pd.DataFrame) -> dict:
    if len(trades) == 0:
        return dict(n=0)
    r = trades["R"].values
    wins, losses = r[r > 0], r[r <= 0]
    gross_p, gross_l = r[r > 0].sum(), -r[r <= 0].sum()
    eq = np.cumsum(r)
    dd = float((np.maximum.accumulate(eq) - eq).max())
    streak = cur = 0
    for x in r:
        cur = cur + 1 if x <= 0 else 0
        streak = max(streak, cur)
    top5 = float(np.sort(r)[::-1][:5].sum() / gross_p) if gross_p > 0 else np.nan
    yearly = trades.groupby(trades["entry_time"].dt.year)["R"].agg(["count", "mean", "sum"])
    return dict(
        n=int(len(r)), win_rate=float((r > 0).mean()),
        avg_win_R=float(wins.mean()) if len(wins) else 0.0,
        avg_loss_R=float(losses.mean()) if len(losses) else 0.0,
        EV_R=float(r.mean()), total_R=float(r.sum()),
        PF=float(gross_p / gross_l) if gross_l > 0 else np.inf,
        maxDD_R=dd, max_losing_streak=int(streak),
        top5_profit_share=top5,
        yearly={int(y): dict(n=int(v["count"]), EV_R=round(float(v["mean"]), 3), total_R=round(float(v["sum"]), 1))
                for y, v in yearly.iterrows()},
    )


def conservative_EV_R(m: dict, haircut_wr: float = 0.05) -> float:
    """保守的EV(docs/03): 勝率-5%pt、平均利益×0.85、平均損失×1.15"""
    if m.get("n", 0) == 0:
        return np.nan
    wr = max(m["win_rate"] - haircut_wr, 0)
    return wr * m["avg_win_R"] * 0.85 + (1 - wr) * m["avg_loss_R"] * 1.15

# -*- coding: utf-8 -*-
"""ライブ・シグナルアラートエンジン(PAPER_TRADE〜半自動execution model B の道具)

位置づけ(docs/04, docs/05):
  - 本エンジンは【発注しない】。検証を通った戦略のシグナルを実相場で判定し、
    音アラート＋発注案(出力形式A)を提示し、logs/signals/ に全判定を記録するだけ。
    実際の発注はユーザーが手動で行う(松井証券FX規程第9条によりbot発注は禁止)。
  - docs/04 の PAPER_TRADE ステージ「実相場でシグナルのみ記録・最低20シグナル」の記録体制であり、
    priority_queue の P2-14「ペーパートレード記録体制」に対応する。
  - 承認前戦略は shadow モード(音を鳴らさず記録のみ)。APPROVED 戦略のみ alert モード。

安全原則(config/risk_limits.json, docs/05 を厳守):
  - 判定前に logs/daily/state_YYYY-MM-DD.json を必ず読む。読めなければ全件 NO_TRADE。
  - halt_flags / 日次上限 / 連敗 / イベント窓 / スプレッド悪化 / EV閾値 未達 は NO_TRADE。
  - エラー後の自動再送信・無人発注は一切しない。認証情報は受け取らない・保持しない。

株式デイトレ(C:\\dev\\daytrade)の rt_engine の運用ノウハウ(音アラート＋ペーパーEV測定＋
サイズ規律)を、FXの制約(発注禁止=提案のみ・24hセッション・pips/スワップ)に適合させたもの。
"""
from __future__ import annotations
import json, sys, time

# Windowsでstdoutがパイプ/リダイレクトされるとcp932になり、絵文字(🔔等)で
# UnicodeEncodeErrorクラッシュする(シグナル成立時に限って落ちる)。UTF-8に強制。
for _s in (sys.stdout, sys.stderr):
    try:
        if _s.encoding and _s.encoding.lower() not in ("utf-8", "utf8"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Protocol

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PIP = 0.01                       # USD/JPY 1pip = 0.01円
JST = timezone(timedelta(hours=9))
RISK = json.loads((ROOT / "config" / "risk_limits.json").read_text(encoding="utf-8"))


# ---------- シグナル・戦略インターフェース ----------
@dataclass
class Signal:
    direction: int               # +1=BUY / -1=SELL / 0=NONE
    sl_pips: float
    tp_pips: Optional[float]
    est_EV_R: float              # バックテスト由来の想定EV(R)
    est_conservative_EV_R: float # 保守EV(docs/03 の haircut 済)
    regime: str = ""
    note: str = ""


class LiveStrategy(Protocol):
    """検証を通った戦略は、確定バー列から最新の判定を返す evaluate を実装する。
    ★エントリーは『確定バーの情報のみ』(ルックアヘッド厳禁・docs/04)。approved で shadow を外す。"""
    name: str
    version: str
    approved: bool
    def evaluate(self, bars: pd.DataFrame) -> Optional[Signal]: ...


# ---------- レート供給(アダプタ) ----------
class RateSource(Protocol):
    def poll(self) -> Optional[pd.DataFrame]:
        """確定済みM1バー列(time_utc,open,high,low,close,bid,ask...)を返す。新規バーが無ければ同じ列で可。"""
        ...


class ReplaySource:
    """検証/スモーク用: DataFrame を1バーずつ再生。live松井レートは読取専用・手動同席のため別途アダプタ化。"""
    def __init__(self, df: pd.DataFrame, warmup: int = 60):
        self.df = df.reset_index(drop=True); self.i = warmup
    def poll(self):
        if self.i >= len(self.df): return None
        window = self.df.iloc[: self.i + 1]; self.i += 1
        return window


# ---------- 安全ゲート ----------
def load_daily_state() -> Optional[dict]:
    """当日の日中状態。読めなければ None → 全件 NO_TRADE(docs/05)。"""
    p = ROOT / "logs" / "daily" / f"state_{datetime.now(JST):%Y-%m-%d}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_no_trade_windows() -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    p = ROOT / "data" / "calendar" / "no_trade_windows.json"
    if not p.exists(): return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        wins = []
        for w in (data if isinstance(data, list) else data.get("windows", [])):
            wins.append((pd.Timestamp(w["start"]).tz_convert("UTC") if pd.Timestamp(w["start"]).tzinfo
                         else pd.Timestamp(w["start"], tz="UTC"),
                         pd.Timestamp(w["end"], tz="UTC") if not pd.Timestamp(w["end"]).tzinfo
                         else pd.Timestamp(w["end"]).tz_convert("UTC")))
        return wins
    except Exception:
        return []


def gate_checks(sig: Signal, spread_pips: float, bar_time_utc, state: Optional[dict],
                windows, max_spread_pips: float = 1.0) -> list[str]:
    """通らなかったチェックのリストを返す(空=TRADE可)。docs/04・risk_limits 準拠。"""
    fail = []
    if state is None:
        return ["DAILY_STATE_UNREADABLE"]        # 読めない=最優先で全件NO_TRADE
    if state.get("halt_flags"):
        fail.append("HALT_" + ",".join(state["halt_flags"]))
    if state.get("trades_today", 0) >= RISK["daily"]["max_trades"]:
        fail.append("MAX_TRADES")
    if state.get("consecutive_losses", 0) >= RISK["streak_and_drawdown"]["max_consecutive_losses_before_halt"]:
        fail.append("STREAK_HALT")
    if state.get("economic_daily_loss_jpy", 0) >= RISK["daily"]["warning_stop_line_jpy"]:
        fail.append("DAILY_WARNING")
    if any(s <= bar_time_utc <= e for s, e in windows):
        fail.append("EVENT_WINDOW")
    if spread_pips > max_spread_pips:
        fail.append(f"SPREAD_WIDE_{spread_pips:.2f}")
    ev = RISK["ev_thresholds"]
    if sig.est_EV_R < ev["min_net_EV_R"]:
        fail.append("EV_BELOW_MIN")
    if sig.est_conservative_EV_R < ev["min_conservative_net_EV_R"]:
        fail.append("CONS_EV_BELOW_MIN")
    return fail


# ---------- サイズ(発注案) ----------
def position_units(sl_pips: float, micro_live: bool = False) -> int:
    """標準リスク額 ÷ (SL幅×1pip価値) を1,000通貨単位に丸め。USD/JPYは1pip=0.01円/通貨。"""
    risk_jpy = RISK["per_trade"]["micro_live_max_risk_jpy"] if micro_live else RISK["per_trade"]["standard_risk_jpy_at_500k"]
    if sl_pips <= 0: return 0
    units = risk_jpy / (sl_pips * PIP)          # 1通貨あたりSL幅の円損失=sl_pips*PIP
    return int(units // 1000 * 1000)


# ---------- ログ ----------
def log_signal(rec: dict):
    p = ROOT / "logs" / "signals" / f"{datetime.now(JST):%Y-%m-%d}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def beep():
    try:
        import winsound; winsound.Beep(1200, 250)
    except Exception:
        print("\a", end="", flush=True)


# ---------- メインループ ----------
def run(strategy: LiveStrategy, source: RateSource, poll_sec: float = 1.0, micro_live: bool = False):
    windows = load_no_trade_windows()
    mode = "alert" if getattr(strategy, "approved", False) else "shadow"
    print(f"=== FXシグナルアラート [{strategy.name} v{strategy.version}] mode={mode} (発注はしない・提案のみ) ===")
    if mode == "shadow":
        print("※未承認戦略のため shadow: 音を鳴らさず logs/signals に記録のみ(PAPER_TRADE用)")
    last_sig_key = None
    while True:
        bars = source.poll()
        if bars is None or len(bars) < 2:
            time.sleep(poll_sec);  # replay枯渇 or 起動直後
            if bars is None: print("レート供給終了"); break
            continue
        bar = bars.iloc[-1]
        bt = pd.Timestamp(bar["time_utc"]); bt = bt.tz_localize("UTC") if bt.tzinfo is None else bt
        spread_pips = float((bar.get("ask", bar["close"]) - bar.get("bid", bar["close"])) / PIP) if "ask" in bar else 0.4
        sig = strategy.evaluate(bars)
        state = load_daily_state()
        now = datetime.now(JST).isoformat(timespec="seconds")
        if not sig or sig.direction == 0:
            log_signal(dict(ts=now, strategy=strategy.name, version=strategy.version, signal="NONE",
                            decision="NO_TRADE", failed_checks=[], net_EV_R=0, conservative_net_EV_R=0,
                            spread_pips=round(spread_pips, 2), regime="", note="no signal"))
            time.sleep(poll_sec); continue
        fails = gate_checks(sig, spread_pips, bt, state, windows)
        decision = "TRADE" if not fails else "NO_TRADE"
        side = "BUY" if sig.direction > 0 else "SELL"
        rec = dict(ts=now, strategy=strategy.name, version=strategy.version, signal=side,
                   decision=decision, failed_checks=fails, net_EV_R=round(sig.est_EV_R, 3),
                   conservative_net_EV_R=round(sig.est_conservative_EV_R, 3),
                   spread_pips=round(spread_pips, 2), regime=sig.regime, note=sig.note)
        log_signal(rec)
        key = f"{side}:{bt:%Y%m%d%H%M}"
        if decision == "TRADE" and key != last_sig_key:
            last_sig_key = key
            units = position_units(sig.sl_pips, micro_live)
            px = float(bar["close"]); slp = sig.sl_pips
            sl_px = px - sig.direction * slp * PIP
            tp_px = px + sig.direction * sig.tp_pips * PIP if sig.tp_pips else None
            max_loss = int(units * slp * PIP)
            if mode == "alert":
                beep()
            print(f"\n🔔[{now}] 発注案(手動執行) {strategy.name} {side}  ※{'音あり' if mode=='alert' else 'shadow'}")
            print(f"   USD/JPY {side} {units:,}通貨 @≈{px:.3f}  SL {sl_px:.3f}({slp:.0f}pips) "
                  f"TP {('%.3f'%tp_px) if tp_px else '—'}  想定最大損失≈{max_loss:,}円")
            print(f"   EV_R {sig.est_EV_R:+.2f}(保守{sig.est_conservative_EV_R:+.2f}) spread{spread_pips:.2f}pips {sig.note}")
            print(f"   → 注文確認画面と1対1照合してから手動発注(docs/05)。不一致なら発注しない。")
        elif decision == "NO_TRADE":
            print(f"[{now}] NO_TRADE {side} ({','.join(fails)})")
        time.sleep(poll_sec)


if __name__ == "__main__":
    print("これは道具モジュール。戦略とレート源を与えて run() を呼ぶ。スモークテストは scripts/live/_smoke.py 参照。")

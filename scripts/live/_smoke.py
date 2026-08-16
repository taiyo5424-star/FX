# -*- coding: utf-8 -*-
"""signal_alert_engine のスモークテスト(合成データ・発注なし)。
戦略とレート源を与えてループ・安全ゲート・ログ・発注案の提示が動くことを確認する。
実データ(data/usdjpy_m1.parquet)が無くても動くよう合成M1を生成。"""
import json, math
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pandas as pd
import signal_alert_engine as E

ROOT = E.ROOT
JST = timezone(timedelta(hours=9))


def synth_bars(n=200, start=150.00):
    """ゆるやかな合成USD/JPY M1(BID基準+擬似スプレッド)。乱数非依存(決定的)。"""
    rows = []
    t0 = pd.Timestamp("2026-07-18 00:00", tz="UTC")
    px = start
    for i in range(n):
        px += 0.02 * math.sin(i / 7) + 0.005 * math.cos(i / 3)   # 決定的な揺れ
        hi = px + 0.03; lo = px - 0.03
        rows.append(dict(time_utc=t0 + pd.Timedelta(minutes=i), open=px - 0.005, high=hi, low=lo,
                         close=px, bid=px - 0.002, ask=px + 0.002))
    return pd.DataFrame(rows)


class DemoStrategy:
    """デモ専用(★実運用禁止・approvedは検証通過後のみTrue)。
    直近20本の平均から-0.10円以上下振れ→BUY(仮の逆張り)。EVはダミー。"""
    name = "DEMO_meanrev"; version = "0.0"; approved = False
    def evaluate(self, bars):
        c = bars["close"]
        if len(c) < 20: return None
        dev = c.iloc[-1] - c.iloc[-20:].mean()
        if dev <= -0.10:
            return E.Signal(direction=+1, sl_pips=12, tp_pips=18, est_EV_R=0.22,
                            est_conservative_EV_R=0.08, regime="demo", note=f"dev{dev:+.2f}円")
        if dev >= 0.10:
            return E.Signal(direction=-1, sl_pips=12, tp_pips=18, est_EV_R=0.22,
                            est_conservative_EV_R=0.08, regime="demo", note=f"dev{dev:+.2f}円")
        return None


def write_state(**over):
    st = dict(date=f"{datetime.now(JST):%Y-%m-%d}", equity_jpy=500000, realized_pnl_jpy=0,
              unrealized_pnl_jpy=0, execution_costs_jpy=0, ai_cash_cost_jpy=0, ai_shadow_cost_jpy=0,
              economic_daily_loss_jpy=0, trades_today=0, consecutive_losses=0,
              remaining_risk_budget_jpy=20000, halt_flags=[], last_updated="smoke")
    st.update(over)
    p = ROOT / "logs" / "daily" / f"state_{datetime.now(JST):%Y-%m-%d}.json"
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    return p


def count_today_signals():
    p = ROOT / "logs" / "signals" / f"{datetime.now(JST):%Y-%m-%d}.jsonl"
    if not p.exists(): return 0, 0
    lines = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    trades = sum(1 for r in lines if r["decision"] == "TRADE")
    return len(lines), trades


if __name__ == "__main__":
    print("### ケース1: 正常状態(approved=True で音・発注案が出る) ###")
    write_state()
    df = synth_bars()
    strat = DemoStrategy(); strat.approved = True
    E.position_units  # ref
    E.run(strat, E.ReplaySource(df, warmup=25), poll_sec=0, micro_live=False)
    n, tr = count_today_signals()
    print(f"\n→ signalsログ {n}行 / うちTRADE {tr}件")

    print("\n### ケース2: 日次警戒ライン到達 → 全件NO_TRADE ###")
    write_state(economic_daily_loss_jpy=17000)
    df2 = synth_bars(n=60)
    E.run(DemoStrategy(), E.ReplaySource(df2, warmup=25), poll_sec=0)  # shadow(approved=False)
    print("→ ケース2は DAILY_WARNING で全て NO_TRADE のはず(上のログ末尾を確認)")

    print("\n### ケース3: daily_state 欠損 → 全件NO_TRADE(安全側) ###")
    p = ROOT / "logs" / "daily" / f"state_{datetime.now(JST):%Y-%m-%d}.json"
    p.unlink(missing_ok=True)
    E.run(DemoStrategy(), E.ReplaySource(synth_bars(n=45), warmup=25), poll_sec=0)
    print("→ ケース3は DAILY_STATE_UNREADABLE で全て NO_TRADE のはず")
    write_state()  # 後片付けで戻す
    print("\n✅ スモーク完了(発注は一切していない・logs/signals に記録)")

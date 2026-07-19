# -*- coding: utf-8 -*-
"""ポジションサイズ計算機(ユーザーの手動発注支援)
config/risk_limits.json のリスク上限に基づき、SL幅から発注数量を計算する。
使い方:
  python3 scripts/ops/position_size.py --sl 25            # SL 25pips、標準リスク
  python3 scripts/ops/position_size.py --sl 25 --equity 480000 --risk-jpy 2400
出力: 発注数量(通貨単位・万通貨)、SL到達時損失、リスク%の確認表
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIP_VALUE_PER_10K = 100.0   # USD/JPY 1万通貨あたり1pip(0.01円)= 100円


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sl", type=float, required=True, help="SL幅(pips)")
    ap.add_argument("--equity", type=float, default=None, help="現在残高(円)。省略時はconfig初期値")
    ap.add_argument("--risk-jpy", type=float, default=None, help="リスク額指定(円)。省略時は残高0.5%%")
    args = ap.parse_args()

    cfg = json.loads((ROOT / "config" / "risk_limits.json").read_text(encoding="utf-8"))
    equity = args.equity or cfg["account"]["initial_equity_jpy"]
    std_pct = cfg["per_trade"]["standard_risk_pct_of_equity"]
    abs_max = cfg["per_trade"]["absolute_max_risk_jpy"]

    risk = args.risk_jpy if args.risk_jpy is not None else equity * std_pct
    capped = min(risk, abs_max)
    if capped < risk:
        print(f"注意: リスク指定{risk:,.0f}円は絶対上限{abs_max:,.0f}円に切り下げ")
    risk = capped

    units_10k = risk / (args.sl * PIP_VALUE_PER_10K)      # 万通貨
    units = int(units_10k * 10000 // 1000 * 1000)          # 1000通貨単位に切り捨て
    actual_loss = units / 10000 * args.sl * PIP_VALUE_PER_10K

    print(f"残高            : {equity:,.0f} 円")
    print(f"リスク予算      : {risk:,.0f} 円({risk / equity * 100:.2f}%)")
    print(f"SL幅            : {args.sl:.1f} pips")
    print(f"発注数量        : {units:,} 通貨({units / 10000:.1f}万通貨、1000通貨単位切捨て)")
    print(f"SL到達時損失    : 約 {actual_loss:,.0f} 円({actual_loss / equity * 100:.2f}%)")
    if units < 1000:
        print("警告: 最小取引単位未満。SL幅が広すぎるか、リスク予算が小さすぎます → 見送り")
    if actual_loss > cfg["daily"]["max_loss_jpy"] / 3:
        print("警告: 1取引の想定損失が日次上限の1/3超。設計を見直してください")


if __name__ == "__main__":
    main()

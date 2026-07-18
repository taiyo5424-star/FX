# 06. Champion / Challenger 運用方式

## 現在の構成(2026-07-06)

- Champion:**なし**(APPROVED戦略0件のため、ライブ取引は全面停止状態が正常)
- Challenger:candidates/batch_001 の15仮説(すべてIDEA)

## 役割定義

### Champion
- ライブ取引に使える唯一のカテゴリ(APPROVED+ユーザー承認済み)
- 稼働条件:日次損失20,000円・1取引5,000円の枠内 / Fable5常時利用なしで機械実行可能
- 同時稼働Championは**最大2戦略**まで(相関の高い戦略の同時稼働は不可)

### Challenger
- ペーパートレードから開始。ユーザー承認後にMICRO_LIVE可
- 通常ロット使用禁止(Championへの昇格まで)

## 昇格判定(Challenger → Champion)

すべて充足+ユーザー明示承認が必要:
- ペーパートレードまたはMICRO_LIVE実測で conservative_net_EV_R > 0
- 最大DDがChampion同等以下 / スリッページ・AIコスト耐性確認済み
- Fable5なしで機械実行可能 / NO_TRADE判断が適切に機能
- Skeptic Agent審査で過剰最適化疑義なし
- 既存Championとの相関が低い、またはChampionを明確に上回る

## 降格・停止判定(Champion → PAUSED)

docs/07の劣化検知条件(直近20取引net_EV_R<=0等)に1つでも該当したら
自動でPAUSEDにし、新規シグナルを無効化。再開はユーザー承認後のみ。

## バージョン管理

- ルール変更は必ず新version作成(旧versionの上書き禁止)
- 新versionはPAPER_TRADEからやり直し(検証済みなのは旧versionだけ)
- 旧versionとの並行ペーパー比較を2週間以上行ってから昇格判定

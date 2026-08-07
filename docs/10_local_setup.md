# 10. ローカル環境セットアップ(Windows / Codex協働用)

目的: クラウド(Routine)を一次系としたまま、あなたのPCでも全ツールを動かし、
Codex CLI・Claude Code・あなたの三者で同じリポジトリを回せるようにする。

## 位置づけ(重要)

- **「移行」ではなく「複線化」**。真実のソースはGitHubリポジトリ
  (taiyo5424-star/fx、ブランチ claude/fx-trading-strategy-i2jwi7)。
  クラウドRoutineはそのまま動き続ける。ローカルは
  ①音アラート(画面同席時)②手動での判定・分析③Codexとの開発、を担う。
- CodexもClaudeも、リポジトリ直下の **AGENTS.md** を必ず読む
  (Codexは自動で読む仕様。ガードレール=発注禁止・OOS再参照禁止等はそこに集約)。

## セットアップ手順(初回のみ、約20分)

```powershell
# 1. Python 3.11+ と Git を導入済みであること(python --version / git --version)
git clone https://github.com/taiyo5424-star/fx.git
cd fx
git checkout claude/fx-trading-strategy-i2jwi7

# 2. 仮想環境と依存
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 3. データ再生成(gitignore対象のため初回クローン後は必須。計15分程度)
python scripts\data\download_histdata.py
python scripts\data\download_dgs10.py

# 4. 動作確認(すべて発注なし・安全)
python scripts\live\_smoke.py                 # ✅3ケース通ればOK
python scripts\backtest\runner_c017.py        # 「LOCKED」表示が正常
python scripts\live\morning_signal_check.py   # 週末はDATA_STALEが正常
```

## 日常の使い方

| 場面 | コマンド |
|---|---|
| 画面に同席して音アラート | `python scripts\live\signal_alert_engine.py`(戦略とレート源を与えてrun()。デモは_smoke.py参照) |
| 朝判定を手動で | `python scripts\live\morning_signal_check.py` |
| 発注前のサイズ計算 | `python scripts\ops\position_size.py --sl 25` |
| 急変チェック | `python scripts\ops\intervention_detector.py` |
| 取引後の記録 | `python scripts\ops\daily_state.py trade-result --pnl -2400` |
| スプレッドを見かけたら | `python scripts\ops\log_spread.py 162.341 162.343` |

### 朝判定のローカル自動実行(任意・クラウドの冗長化)

クラウドRoutineが一次系なので必須ではない。PC常時起動なら:

```bat
:: cmd.exe で実行(PowerShellの場合は ^ を使わず1行で)
schtasks /create /tn "FX-morning-signal" /sc weekly /d MON,TUE,WED,THU,FRI ^
  /st 08:15 /tr "C:\path\to\fx\.venv\Scripts\python.exe C:\path\to\fx\scripts\live\morning_signal_check.py"
```

二重実行しても冪等(ログ追記のみ・発注なし)なので衝突しない。

## Codexとの協働(PDCA)

1. **Plan**: 課題を Issue または research/priority_queue.md に記載
2. **Do**: Codexは `codex/*` ブランチで作業(AGENTS.mdの規律内で)
3. **Check**: 主張は必ずランナー出力(research/のJSON)で裏取り。
   クラウド側Claudeまたはローカル `python scripts\live\_smoke.py` 等で検証
4. **Act**: PRで claude/fx-trading-strategy-i2jwi7 に統合

**Codexに最初に伝える一言の例**:
「リポジトリ直下のAGENTS.mdを読んで従って。特に発注実装の禁止と
旧OOS期間の再参照禁止は絶対条件。」

## Claudeセッション自体のWeb⇔ローカル引き継ぎ

プロジェクト(コード)だけでなく、Claudeとの**セッション(会話の続き)**も移動できる:

- **Web → ローカル**: PCにClaude Codeを導入後、`claude --teleport` を実行すると
  セッション一覧から選んで会話履歴・ブランチごとローカルに引き継げる
  (条件: 同じclaude.aiアカウント / リポジトリをclone済み / 作業ツリーが綺麗)。
  引き継ぎ後はローカルが独立コピーになる(Web側とは以後同期しない)。
- **ローカル → Web**: `claude --cloud "タスク内容"` で新規クラウドセッションを起動
  (push済みのコミットが引き継がれる)。デスクトップアプリなら「Continue in」でも可。
- **どちらでも文脈が通じる理由**: リポジトリ直下の CLAUDE.md / AGENTS.md を
  Web・ローカル両方のClaude(とCodex)が自動で読むため。**状態の真実は常に
  このリポジトリ**(会話が消えてもリポジトリだけで再開可能な設計)。

### Claude Code のローカル導入(Windows、1コマンド)

```powershell
irm https://claude.ai/install.ps1 | iex
```

実行後 `claude` と打つとブラウザでログイン → そのまま使用可。
確認は `claude doctor`。

## トラブルシュート

- `ModuleNotFoundError` → 仮想環境の有効化忘れ(`.venv\Scripts\activate`)
- HistDataダウンロード失敗 → 月初は先月分未公表のことがある。翌週再実行
- 文字化け → PowerShellで `chcp 65001`(UTF-8)。パイプ/リダイレクト時の
  UnicodeEncodeError対策はコード側で対応済み(stdout自動UTF-8化)だが、
  恒久設定するなら `setx PYTHONUTF8 1` を1回実行
- Dukascopyの特定日欠損(例: 2026-06-28〜07-01)→ 既知。前進検証は自動でスキップ

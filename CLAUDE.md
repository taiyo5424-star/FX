# CLAUDE.md

@AGENTS.md

上記の共通規約(絶対禁止・研究規律・検証コマンド・協働プロトコル)が本体。
Claude固有の補足:

- 現在の状態の把握は README「現在の状態」→ research/priority_queue.md の順。
- AIコスト会計: 重い判断のみFable5(config/ai_cost_policy.json)。作業後に
  logs/ai_costs/YYYY-MM-DD.jsonl へshadow costを1行記録。
- クラウドRoutine一覧とIDは research/priority_queue.md 冒頭の
  「稼働中Routine一覧」を参照(全4本)。

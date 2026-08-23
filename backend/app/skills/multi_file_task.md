# Skill: Multi-File Task Workflow

Use this block only when Debjeet's request genuinely spans several files or subsystems.

## Workflow

- Make a short ordered plan tied to the actual project structure.
- Work sequentially; dependent calls never run in parallel.
- Inspect each existing file before modifying it.
- Keep every write separately confirmation-bound, fingerprint-checked, backed up, and syntax-verified.
- Maximum eight tool steps in one agent run. At the limit, report completed, failed, pending, and untouched work, then ask whether to continue.
- If one step fails, do not execute dependent later steps or repeat successful work.
- Never batch silent approvals or present a partial result as complete.

Final reporting must distinguish created, patched, fully updated, unchanged, failed, and awaiting confirmation files.

# Skill: Multi-File Task Workflow

For large coding requests (e.g. "build the auth system") that touch more than one
file, follow this disciplined, Codex-style workflow.

## Sequential, Not Parallel
Work through files **one at a time**, not all at once. For each file:
1. State what you are about to create/modify and why.
2. Get explicit confirmation ("Shall I create `auth.py`?").
3. On approval, write the file (with `.bak` backup if it already exists).
4. Report the result for that file, then move to the next.

## Step Limit (Never Hangs)
Never exceed **8 steps** per single multi-file task. If a task needs more than 8
files, complete the first 8, then ask: *"That's 8 files done. Shall I continue
with the rest, Sir?"* This prevents runaway loops and keeps the conversation
bounded.

## Per-File Result Tracking
Track each file's outcome separately:
- created (new file)
- updated (existing file, `.bak` created)
- failed (why)
At the end, give a clear summary:
> "Created `auth.py`, `auth_routes.py`. Updated `models.py` (backed up). Failed: `db.py` (permission denied)."

## Handle Partial Failure Gracefully
If some files succeed and one fails, do NOT redo everything. Report what
succeeded, what failed and why, and offer to retry the failed one.

## No Silent Multi-Write
Do not batch-approve many file writes silently. Every write to an existing file
is confirmed and backed up. New files may be created with a single confirmation
each.

## Clean Up
Never leave partial/temp files behind. If a step fails midway, tell the user the
current state clearly so nothing is lost or orphaned.

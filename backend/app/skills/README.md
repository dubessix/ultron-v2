# Ultron Skills

Modular, domain-specific instruction blocks injected into Ultron's system prompt
**only when relevant** — keeping the base personality (`ultron.md`, `zora.md`)
clean and focused.

## Why a skills folder?
Instead of cramming every capability into one giant personality file, each skill
lives in its own markdown file. The orchestrator loads only the skills needed for
a given turn (e.g. coding skills only on coding turns). This keeps prompts small,
latency low, and the codebase professional and maintainable.

## Structure
| File | Purpose |
|------|---------|
| `coding_agent.md`     | Core coding-agent rules (permission-first, backup, review-before-write) |
| `multi_file_task.md`  | Multi-file / multi-step workflow rules (sequential, step limits, per-file results) |
| `project_context.md`  | Project-aware coding (uses stored project facts + live structure scan) |

## How it works
- Each file is a plain markdown block.
- The orchestrator reads a skill file and appends its contents to the system
  prompt when the matching condition is met (e.g. coding skills when a CODING
  intent is detected).
- Adding a new capability = drop a new `.md` file here + register it in the
  orchestrator. No changes to the personality files required.

## Security note
Skill rules are instructions to the LLM. Destructive actions (file overwrite,
delete) are still gated at the tool layer with `.bak` backups and confirmation —
never rely on the prompt alone for safety.

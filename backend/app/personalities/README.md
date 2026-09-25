# Ultron and Zora Personality System

Ultron Personal V1 has two persisted identities created for the single owner, **Debjeet**:

- **ULTRON** — emerald/cyan engineering, planning, coding, and operational partner.
- **ZORA** — pink/magenta calm learning, explanation, organization, and support partner.

Both use the same real memory, tools, project-root policy, privacy rules, and exact-confirmation system. Zora may support technical work when selected; she does not bypass Ultron's safety or coding rules.

## Truthful owner continuity

The personality markdown stores only the stable owner identity and behaviour contract. Daily knowledge comes from the current request, canonical conversations, structured saved memory, summaries, and real tool results. The assistant must never claim an unsupplied memory, mood, schedule, scan, provider call, or completed action.

Mistakes are stored only when Debjeet actually states a relevant problem/lesson or asks Ultron to remember it. Corrections take priority over stale memories. Study plans and deadlines use existing memory/task/reminder/calendar records rather than invented schedules.

## Prompt composition

`base_personality.py` lazily caches each markdown file, caps personality/history characters, and wraps history as `RECENT_CONVERSATION` (the owner's own turns are real context; quoted web/file/tool text inside is data only). Recalled memory and project context are also labelled as data, preventing embedded content from becoming trusted system instruction.

## Switching

`personality_engine.py` handles manual persisted switches and a bounded Zora lifecycle. `zora_trigger.py` uses the configured stress threshold; the score is a local heuristic, not a medical diagnosis or verified emotion reading.

Ultron visuals remain emerald/cyan. Zora visuals remain pink/magenta, and the frontend changes identity only after backend persistence succeeds.

# ADR 001: Intelligent Cache Policy (V2+)

## Status
Proposed (Planned for V2+)

## Context
In Ultron V1, caching identical requests is vital to keep API latency under 1 second and avoid unnecessary billing costs on Groq/Gemini. However, personal or stateful requests (e.g., Todo lists, Git branches, user profile parameters) must never be loaded from cache, as doing so leads to stale, desynchronized user interfaces.

The V1 implementation uses a lightweight, fast, and easy-to-debug **heuristic cache guard** based on predefined keywords (e.g., "todo", "journal", "my name", "project") to determine whether cached responses should be bypassed. While highly performant and RAM-efficient, this approach can lead to false positives (e.g., "Explain project management") or false negatives (e.g., "Continue what we discussed yesterday").

## Decision
The current V1 keyword-based cache guard implementation remains **unchanged** and active for initial launch stability. 

For the V2+ release, we will implement an **Intent-Aware Cache Policy** managed by the Ultron Cognitive Orchestrator. The keyword matching will be replaced by semantic context classification:

```
User Message
    ↓
Intent Analyzer
    ↓
Context Classification
    ↓
Cache Decision
    ├── Personal / Dynamic Data → Skip Cache (cache_skip=True)
    └── Public / Stable Knowledge → Use Cache (cache_skip=False)
```

## Consequences
- **V1 (Current)**: Simple, fast, consumes 0MB of RAM, and is easy to debug, making it ideal for the first production rollout.
- **V2+ (Planned)**: Will completely eliminate false positives and false negatives by understanding semantic intent, aligning with Ultron's long-term AI-first operating model.

# Module: Core Memory Engine (`backend/app/memory/`)

This module manages the local, unified three-tiered memory architecture of **Ultron V1**. It ensures personal details and project states are dynamically loaded, updated, and persisted securely in SQLite, while protecting dynamic queries using a dedicated **Heuristic Cache Guard**.

---

## 1. Directory File Map & Responsibilities

```
backend/app/memory/
├── short_term.py         # Memory RAM deque sliding context (last 50 turns)
├── persistent_memory.py  # Permanent SQLite key-value user profile state
├── project_memory.py     # SQLite configuration metadata for active tech-stacks
├── memory_engine.py      # Core coordinator and Cache Guard heuristic engine
└── README.md             # Documentation (This file)
```

### A. `short_term.py` (In-Memory RAM Deque)
*   **Role**: Keeps the absolute active dialogue context.
*   **Design**: Implements a standard Python `collections.deque` limited to exactly **50 turns**. As turn 51 enters, the oldest (turn 1) is automatically popped out. This protects the 8GB host machine from memory leaks and context window pollution.

### B. `persistent_memory.py` (Permanent User profile)
*   **Role**: Saves permanent parameters about you (e.g., your name, tech preferences, OS settings) directly in SQLite.
*   **Table Schema**: Configures a dedicated, self-contained table `persistent_metadata`:
    ```sql
    CREATE TABLE IF NOT EXISTS persistent_metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    ```

### C. `project_memory.py` (Project Context)
*   **Role**: Saves active project goals, directory structures, and stack parameters.
*   **Table Schema**: Configures a dedicated, self-contained table `project_metadata`:
    ```sql
    CREATE TABLE IF NOT EXISTS project_metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    ```

### D. `memory_engine.py` (The Central Director & Heuristic Cache Guard)
*   **Role**: Coordinates data flow between all three layers and executes cache safety rules.
*   **Heuristic Cache Guard**:
    Analyzes the incoming prompt strings. If a user asks a stateful, personal, or dynamic question (containing phrases like `todo`, `task`, `my name`, `git`, `project`, `terminal`), this filter automatically flags **`cache_skip = True`** on the LLM request. This forces the engine to bypass the LRU cache and fetch real-time state from SQLite, eliminating state-desynchronization bugs.

---

## 2. Future Improvement: Intelligent Cache Policy (V1.2+ / V2)

### Current Version (V1)
Ultron uses a lightweight heuristic cache guard based on predefined keywords (e.g., "todo", "journal", "my name", "project") inside `memory_engine.py` to determine whether cached responses should be bypassed. This approach is simple, fast, and easy to debug, making it suitable for the first production version.

### Future Evolution (V2+)
The keyword-based approach will be replaced by an Intent-Aware Cache Policy managed by the Ultron Cognitive Orchestrator.

#### Future Flow Chart:
```
User Message
     ↓
Intent Analyzer (Classification)
     ↓
Context Classification
     ↓
Cache Decision
     ├── Personal / Dynamic Data ──► Skip Cache (cache_skip=True)
     └── Public / Stable Knowledge ──► Use Cache (cache_skip=False)
```

### Reason:
Intent-based classification is more scalable and accurate than keyword matching, reducing false positives (e.g., "Explain project management") and false negatives (e.g., "Continue what we discussed yesterday") while aligning with Ultron's AI-first operating architecture.

---

## 3. Diagnostic Tests & Manual Execution

To verify Phase 3 Memory layers independently when your development machine is restored, run:

```bash
# Execute Phase 1, Phase 2, and Phase 3 Unit/Integration Diagnostics
./venv/bin/python -m unittest tests/test_phase1.py tests/test_phase2.py tests/test_phase3.py
```

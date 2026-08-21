# Module: LLM Brain Routing Engine (`backend/app/brain/`)

This module manages high-availability, low-latency, and cost-optimized connections to cloud LLM APIs (Groq and Gemini) under a strict **8GB RAM host constraint**.

---

## 1. Directory File Map & Responsibilities

```
backend/app/brain/
├── api_key_manager.py     # State tracker and atomic round-robin key rotator
├── smart_cache.py         # Persistent local LRU-TTL cache manager
├── llm_router.py          # Primary async HTTPX client and fallback coordinator
└── README.md              # Documentation (This file)
```

### A. `api_key_manager.py` (The Key Pool Coordinator)
*   **Role**: Pools 3 Groq and 2 Gemini API keys.
*   **Design**: Defines an active state machine for keys:
    *   `ACTIVE`: Healthy and available in rotation.
    *   `COOLING`: Temporarily locked after encountering an HTTP 429 (Rate Limit) or network timeout. Keys automatically return to `ACTIVE` after their cooldown duration expires.
    *   `FAILED`: Permanently suspended after receiving critical authentication failures (HTTP 401/403) or unrecoverable error status codes.
*   **Rotation**: Implements standard atomic Round-Robin key selection.

### B. `smart_cache.py` (The Persistent LRU Cache)
*   **Role**: Intercepts requests, returning identical query matches in **under 1ms** without hitting external network connections.
*   **RAM Safety**: Employs a strict Least-Recently-Used (LRU) limit capped at exactly **200 items** to prevent memory bloat on an 8GB PC.
*   **Lifecycle**: Auto-restores unexpired rows from `data/cache/smart_cache.json` on boot, and writes active states cleanly back to disk on clean server shutdowns.

### C. `llm_router.py` (The Connection Dispatcher)
*   **Role**: Coordinates the entire cognitive request pipeline.
*   **Execution Flow**:
    1.  Calculates request payload SHA-256 identifier hashes.
    2.  Queries `SmartCache`. On hit, returns instantly.
    3.  On miss, retrieves the next active key for the preferred provider.
    4.  Issues async requests using highly-tuned `httpx.AsyncClient` pools (connection limits: 20 max, 5 keep-alive; timeouts: 30.0s).
    5.  **Exception Handling**: If a 429 rate limit is met, marks the key as `COOLING`, advances the pool cursor, and seamlessly retries.
    6.  **Failover Cascade**: If all Groq keys are exhausted, automatically initiates a failover gateway to Gemini to ensure zero runtime interruptions.

---

## 2. API Key State-Transition Logic

```
                    +--------------------+
                    |    State: ACTIVE   |
                    +---------+----------+
                              |
                     On HTTP 429 / Timeout
                              |
                              v
                    +--------------------+
                    |   State: COOLING   |
                    +---------+----------+
                              |
                     Cooldown Timer Expires
                              |
                              v
                    +--------------------+
                    |    State: ACTIVE   |
                    +--------------------+
```

---

## 3. Future Improvement: Intelligent Cache Policy (V2+)

### Current Version (V1)
Ultron uses a lightweight heuristic cache guard based on predefined keywords (e.g., "todo", "journal", "my name", "project") to determine whether cached responses should be bypassed. This approach is simple, fast, and easy to debug, making it suitable for the first production version.

### Future Evolution (V2+)
The keyword-based approach will be replaced by an Intent-Aware Cache Policy managed by the Ultron Cognitive Orchestrator.

### Reason:
This will reduce false positives and false negatives while aligning with Ultron's AI-first architecture. The V1 implementation remains unchanged.

---

## 4. Diagnostic Tests & Manual Execution

To verify Phase 2 Operations independently when your development machine is restored, run:

```bash
# Execute Phase 2 Unit and Mock Integration Tests
./venv/bin/python -m unittest tests/test_phase2.py
```

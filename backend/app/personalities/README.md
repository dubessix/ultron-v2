# Module: Dual Personalities & Emotion Engine (`backend/app/personalities/` & `backend/app/emotion/`)

This module houses the dual conversational identities of **Ultron** (Technical Senior Developer) and **Zora** (Emotional Co-Pilot/Companion) and orchestrates automated, stress-triggered handoffs.

---

## 1. Directory Structure & File Map

```
backend/app/
├── personalities/
│   ├── personality_engine.py  # Coordinates active profiles and manual transitions
│   ├── ultron_profile.py      # Standard placeholder for future extensions
│   ├── zora_profile.py        # Standard placeholder for future extensions
│   └── README.md              # Documentation (This file)
└── emotion/
    ├── signal_analyzer.py     # Calculates weighted Es Stress Score
    └── zora_trigger.py        # Monitors Es Score against thresholds
```

### A. `personality_engine.py` (The Profile Custodian)
*   **Role**: Enforces prompt tone matrices and matches conversational guidelines.
*   **Manual Switches**: Uses regular expressions to scan prompts for transition keywords:
    *   *To Zora*: `"Switch to Zora"`, `"I need Zora"`, `"Zora come here"`, `"Where is Zora"`.
    *   *To Ultron*: `"Switch to Ultron"`, `"Back to work"`, `"Ultron"`, `"Let's get back to it"`.

### B. `signal_analyzer.py` (The Stress Calculator)
*   **Role**: Computes the sliding-window Stress Score ($E_s$) based on:
    $$E_s = w_1 \cdot C_{err} + w_2 \cdot T_{midnight} + w_3 \cdot D_{ratio} + w_4 \cdot S_{sentiment}$$
    *   $C_{err}$: Count of consecutive compilation failures (scaled up to 4).
    *   $T_{midnight}$: Temporal check. Work sessions after 11 PM scale stress exponentially.
    *   $D_{ratio}$: Ratio of characters deleted versus characters typed inside the console input box.
    *   $S_{sentiment}$: Scanning density of frustration words (*"hate"*, *"broken"*, *"give up"*, *"stupid"*).

### C. `zora_trigger.py` (The Handoff Orchestrator)
*   **Role**: Monitors the calculated $E_s$ score. If the score exceeds the **`0.75`** threshold, it overrides the system state and triggers an immediate handoff event to Zora.

---

## 2. Diagnostic Tests & Manual Execution

To verify Phase 6 Personalities and Emotional modules independently when your development machine is restored, run:

```bash
# Execute complete unit, integration, and E2E diagnostics across all 6 completed phases
./venv/bin/python -m unittest tests/test_phase1.py tests/test_phase2.py tests/test_phase3.py tests/test_phase4.py tests/test_phase5.py tests/test_phase6.py
```

This test suite verifies:
1.  Manual switching phrase matches and bidirectional state changes.
2.  Weighted $E_s$ scoring outputs under normal and critical stress.
3.  Zora's prompt constraints, verifying absolute exclusion of clinical AI disclaimers.
4.  E2E orchestrator transition pipeline, confirming that high-stress inputs past midnight automatically switch the system personality to Zora before querying cloud clients.

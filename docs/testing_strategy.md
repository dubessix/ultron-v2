# Testing and Release Gates

## Isolation policy

`tests/conftest.py` sets `ULTRON_TEST_MODE` before backend storage imports. SQLite, cache, semantic graph, backups, logs, and generated artifacts resolve below a temporary test root. A production `data/` tree hash is compared before and after pytest.

Standalone unittest discovery is also detected and isolated by `backend.app.runtime_paths`.

## Required automated gates

```bash
python -m pytest -q
python -m unittest discover -s tests -p 'test*.py'
python -m coverage run -m pytest -q
python -m coverage report -m
ruff check backend tests launcher.py setup.py
bandit -q -r backend
python -m pip_audit -r requirements-dev.txt --progress-spinner off
python -m pip check
cd frontend
npm ci
npm audit --audit-level=low
npm run build
```

The coverage gate measures application code (`backend` and `launcher`) and currently prevents regression below the configured threshold. Coverage is not described as total or proof of correctness.

## Important regression areas

- provider/model cache isolation and key state;
- exact action confirmation and path boundaries;
- sequential coding writes and terminal child cleanup;
- SSRF/redirect/download limits;
- project-scoped memory and newest history;
- backup retention, restore lock, rollback, and task cancellation;
- clean wheel resources and external installation;
- loopback launcher health/process lifecycle;
- no fabricated values or false success states.

## Live-check policy

Automated tests mock provider/network/device edges to be deterministic. They do not automatically consume real provider quotas or assume hardware. Live Groq/Gemini/NVIDIA/Tavily/GitHub, Windows, browser GUI, microphone/TTS playback, and Spotify checks are separately marked PASS, FAIL, or BLOCKED.

## Failure handling

A gate failure is fixed or reported; it is never relabelled as success. Tests must not be weakened merely to hide a product defect. A changed test should document the corrected contract (for example replacing an old fabricated-latency expectation with real network counters).

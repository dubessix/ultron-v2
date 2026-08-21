# Project Structure

```text
.
├── backend/app/                 Python application
├── frontend/                    React/Vite source and lockfile
├── tests/                       isolated pytest/unittest regressions
├── docs/                        current operating and technical references
├── config.yaml                  personal runtime defaults
├── launcher.py                  local process owner
├── setup.py                     wheel metadata and runtime assets
├── pyproject.toml               build, Ruff, and coverage gates
├── MANIFEST.in                  source distribution assets
├── requirements.txt             pinned runtime dependencies
├── requirements-dev.txt         test/audit/build dependencies
├── start_ultron.sh              Linux convenience entry
└── start_ultron.bat             Windows convenience entry
```

Generated directories (`.venv`, `node_modules`, `dist`, build outputs, caches, coverage, runtime data) are not committed.

Installed wheels place immutable assets below the installation share directory and writable personal state below `ULTRON_HOME` (or platform default). Source checkouts use the repository as application home unless overridden.

The frontend widget registry lazy-loads all widget components. Backend tool registration is lazy through `ToolRegistry`; runtime behavior is implemented in tool modules rather than documentation claims.

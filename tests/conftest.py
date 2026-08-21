"""Shared pytest safety bootstrap.

All generated state is redirected below one temporary root before backend modules
are imported.  A before/after hash guard proves pytest did not alter production
``data/``.  Standalone unittest runs are isolated by backend.runtime_paths, which
detects the unittest runner before the database/cache modules resolve paths.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PRODUCTION_DATA = (ROOT / "data").resolve()
TEST_ROOT = Path(tempfile.mkdtemp(prefix="ultron_pytest_runtime_")).resolve()

# Set these before importing any backend storage module.
os.environ["ULTRON_TEST_MODE"] = "1"
os.environ["ULTRON_TEST_ROOT"] = str(TEST_ROOT)
# Backward-compatible flags for any external code still checking them.
os.environ["ULTRON_TEST_DB"] = "1"
os.environ["ULTRON_TEST_CACHE"] = "1"


def _snapshot_tree(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    snapshot = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        snapshot[str(path.relative_to(root))] = digest
    return snapshot


_PRODUCTION_BEFORE = _snapshot_tree(PRODUCTION_DATA)

# Imports now resolve all runtime paths below TEST_ROOT.
from backend.app.database import db as _db  # noqa: E402
from backend.app.brain import smart_cache as _cache  # noqa: E402
from backend.app.runtime_paths import assert_safe_test_path  # noqa: E402

assert_safe_test_path(_db.DB_PATH)
assert_safe_test_path(_cache.CACHE_PATH)


@pytest.fixture(autouse=True, scope="session")
def ensure_database_schema():
    """Initialize the isolated schema and enforce production-tree immutability."""
    from backend.app.database.db import get_db_connection
    from backend.app.database.models import initialize_database

    with get_db_connection() as conn:
        initialize_database(conn)
    yield

    production_after = _snapshot_tree(PRODUCTION_DATA)
    shutil.rmtree(TEST_ROOT, ignore_errors=True)
    if production_after != _PRODUCTION_BEFORE:
        changed = sorted(set(_PRODUCTION_BEFORE) ^ set(production_after))
        changed.extend(
            key for key in set(_PRODUCTION_BEFORE) & set(production_after)
            if _PRODUCTION_BEFORE[key] != production_after[key]
        )
        raise AssertionError(
            "Tests modified production data paths: " + ", ".join(sorted(set(changed)))
        )

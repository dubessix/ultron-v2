"""Runtime path policy shared by production code and test runners.

Tests must never touch the user's real ``data`` directory.  Pytest sets an
explicit flag from ``tests/conftest.py``; unittest is also detected from its
module entry point so the documented discovery command is safe when run alone.
All test storage is placed below one process-local temporary root and removed at
process exit.
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

from backend.app.install_paths import APPLICATION_HOME

# Source checkouts keep their existing repository-local data layout. Installed
# wheels use a writable per-user ULTRON_HOME (never site-packages/sys.prefix).
BASE_DIR = APPLICATION_HOME
PRODUCTION_DATA_ROOT = (APPLICATION_HOME / "data").resolve()


def _running_test_command() -> bool:
    """Return True only for an explicit test flag or a pytest/unittest runner."""
    if os.getenv("ULTRON_TEST_MODE") == "1":
        return True
    argv0 = str(sys.argv[0]).lower() if sys.argv else ""
    argv = " ".join(str(arg).lower() for arg in sys.argv)
    return "pytest" in argv0 or "unittest" in argv0 or "-m pytest" in argv or "-m unittest" in argv


TEST_MODE = _running_test_command()
_created_test_root = False

if TEST_MODE:
    configured_root = os.getenv("ULTRON_TEST_ROOT", "").strip()
    if configured_root:
        TEST_ROOT = Path(configured_root).expanduser().resolve()
        TEST_ROOT.mkdir(parents=True, exist_ok=True)
    else:
        TEST_ROOT = Path(tempfile.mkdtemp(prefix="ultron_test_runtime_")).resolve()
        os.environ["ULTRON_TEST_ROOT"] = str(TEST_ROOT)
        _created_test_root = True
else:
    TEST_ROOT = None


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def assert_safe_test_path(path: Path) -> Path:
    """Reject a test path outside TEST_ROOT or inside the production data tree."""
    resolved = Path(path).expanduser().resolve()
    if not TEST_MODE or TEST_ROOT is None:
        return resolved
    if resolved == PRODUCTION_DATA_ROOT or _is_within(resolved, PRODUCTION_DATA_ROOT):
        raise RuntimeError(f"Refusing test access to production data path: {resolved}")
    if not _is_within(resolved, TEST_ROOT):
        raise RuntimeError(f"Test runtime path escapes ULTRON_TEST_ROOT: {resolved}")
    return resolved


def runtime_data_path(*parts: str) -> Path:
    """Resolve a data path under the temporary test root or production data root."""
    root = TEST_ROOT if TEST_MODE and TEST_ROOT is not None else PRODUCTION_DATA_ROOT
    path = Path(root, *parts).resolve()
    if TEST_MODE:
        assert_safe_test_path(path)
    return path


def isolated_test_artifact_path(*parts: str) -> Path:
    """Resolve a generated test artifact path below the isolated test root."""
    if not TEST_MODE or TEST_ROOT is None:
        raise RuntimeError("isolated_test_artifact_path() is only available in test mode")
    path = Path(TEST_ROOT, "artifacts", *parts).resolve()
    assert_safe_test_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _cleanup_created_test_root() -> None:
    if _created_test_root and TEST_ROOT is not None:
        shutil.rmtree(TEST_ROOT, ignore_errors=True)


atexit.register(_cleanup_created_test_root)

"""Resolve source-checkout, installed assets, and writable personal runtime paths."""

from __future__ import annotations

import os
import platform
import shutil
import sys
from importlib import metadata
from pathlib import Path


PACKAGE_SITE_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_ROOT = PACKAGE_SITE_ROOT
_SOURCE_CHECKOUT = (
    (_SOURCE_ROOT / "setup.py").is_file()
    and (_SOURCE_ROOT / "config.yaml").is_file()
    and (_SOURCE_ROOT / "frontend" / "package.json").is_file()
)


def _expand(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve(strict=False)


def _metadata_asset_root() -> Path | None:
    """Locate wheel data through RECORD (works for venv, --user, and --target)."""
    try:
        distribution = metadata.distribution("ultron")
    except metadata.PackageNotFoundError:
        return None
    for entry in distribution.files or []:
        normalized = str(entry).replace("\\", "/")
        if normalized.endswith("share/ultron/config.yaml"):
            return Path(distribution.locate_file(entry)).resolve().parent
    return None


def _find_asset_root() -> Path:
    configured = os.getenv("ULTRON_ASSET_ROOT", "").strip()
    candidates = []
    if configured:
        candidates.append(_expand(configured))
    if _SOURCE_CHECKOUT:
        candidates.append(_SOURCE_ROOT)
    recorded = _metadata_asset_root()
    if recorded is not None:
        candidates.append(recorded)
    # Fallbacks cover pip --target and conventional virtual environments even
    # if distribution metadata is temporarily unavailable.
    candidates.extend(
        [
            PACKAGE_SITE_ROOT / "share" / "ultron",
            Path(sys.prefix).resolve() / "share" / "ultron",
        ]
    )
    for candidate in candidates:
        if (
            (candidate / "config.yaml").is_file()
            and (candidate / "launcher.py").is_file()
            and (candidate / "frontend" / "package.json").is_file()
        ):
            return candidate.resolve(strict=False)
    # Keep a deterministic location so diagnostics can name the missing path.
    return candidates[0].resolve(strict=False) if candidates else _SOURCE_ROOT


def _default_application_home() -> Path:
    configured = os.getenv("ULTRON_HOME", "").strip()
    if configured:
        return _expand(configured)
    if _SOURCE_CHECKOUT:
        return _SOURCE_ROOT
    if platform.system() == "Windows":
        local_app_data = os.getenv("LOCALAPPDATA", "").strip()
        if local_app_data:
            return _expand(str(Path(local_app_data) / "Ultron"))
    xdg_data = os.getenv("XDG_DATA_HOME", "").strip()
    if xdg_data:
        return _expand(str(Path(xdg_data) / "ultron"))
    return (Path.home() / ".ultron").resolve(strict=False)


ASSET_ROOT = _find_asset_root()
APPLICATION_HOME = _default_application_home()
FRONTEND_DIR = ASSET_ROOT / "frontend"
LAUNCHER_PATH = ASSET_ROOT / "launcher.py"
DEFAULT_CONFIG_PATH = ASSET_ROOT / "config.yaml"
ENV_EXAMPLE_PATH = ASSET_ROOT / ".env.example"
ENV_PATH = APPLICATION_HOME / ".env"

_config_override = os.getenv("ULTRON_CONFIG", "").strip()
if _config_override:
    CONFIG_PATH = _expand(_config_override)
elif (APPLICATION_HOME / "config.yaml").is_file():
    CONFIG_PATH = APPLICATION_HOME / "config.yaml"
else:
    CONFIG_PATH = DEFAULT_CONFIG_PATH


def is_source_checkout() -> bool:
    return _SOURCE_CHECKOUT


def ensure_user_config(overwrite: bool = False) -> Path:
    """Copy the bundled default config into the user's writable application home."""
    destination = APPLICATION_HOME / "config.yaml"
    if destination.exists() and not overwrite:
        return destination
    if not DEFAULT_CONFIG_PATH.is_file():
        raise FileNotFoundError(f"Bundled config is missing: {DEFAULT_CONFIG_PATH}")
    APPLICATION_HOME.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".yaml.tmp")
    shutil.copy2(DEFAULT_CONFIG_PATH, temporary)
    os.replace(temporary, destination)
    return destination

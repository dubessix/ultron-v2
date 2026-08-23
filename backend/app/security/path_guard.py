r"""Central allowlist/blocklist policy for every local filesystem tool."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from backend.app.install_paths import CONFIG_PATH
from backend.app.runtime_paths import BASE_DIR, TEST_MODE, TEST_ROOT

_DEFAULT_BLOCKED_ROOTS = [
    "/etc", "/var", "/proc", "/sys", "/boot", "/root", "/dev", "/bin",
    "/sbin", "/lib", "/lib64", "/usr/sbin", "/System", "/Library",
    r"C:\Windows", r"C:\Windows\System32", r"C:\Program Files",
    r"C:\Program Files (x86)",
]
_SENSITIVE_NAMES = {
    ".ssh", ".gnupg", ".aws", ".env", ".git-credentials", ".netrc",
    "credentials", "secrets", "keystore", "id_rsa", "id_ed25519",
}


def _load_security_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
            return (yaml.safe_load(handle) or {}).get("security", {}) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _resolve_config_path(value: str) -> Path:
    expanded = Path(os.path.expandvars(os.path.expanduser(str(value))))
    if not expanded.is_absolute():
        expanded = BASE_DIR / expanded
    return expanded.resolve(strict=False)


def _inside(target: Path, root: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def get_blocked_paths() -> list[str]:
    configured = _load_security_config().get("blocked_directories", []) or []
    values = list(configured) + _DEFAULT_BLOCKED_ROOTS
    resolved = []
    for value in values:
        if not value:
            continue
        text = str(value)
        if ":" in text and os.name != "nt":
            continue
        try:
            path = _resolve_config_path(text)
        except (OSError, RuntimeError, ValueError):
            continue
        normalized = os.path.normcase(str(path))
        if normalized not in resolved:
            resolved.append(normalized)
    return resolved


def get_allowed_paths() -> list[str]:
    """Return effective allowed roots; secure default is the project root only."""
    config = _load_security_config()
    configured = config.get("allowed_directories", []) or []
    env_value = os.getenv("ULTRON_ALLOWED_DIRECTORIES", "").strip()
    if env_value:
        configured = [part for part in env_value.split(os.pathsep) if part]

    if not configured:
        policy = str(config.get("empty_allowed_policy", "project_only")).lower()
        if policy != "project_only":
            # Unknown/unsafe policies fail closed rather than silently allowing /.
            policy = "project_only"
        configured = [str(BASE_DIR)]

    roots = []
    for value in configured:
        try:
            root = _resolve_config_path(str(value))
        except (OSError, RuntimeError, ValueError):
            continue
        normalized = os.path.normcase(str(root))
        if normalized not in roots:
            roots.append(normalized)

    # Tests may write only below their isolated runtime root, never arbitrary /tmp.
    if TEST_MODE and TEST_ROOT is not None:
        test_root = os.path.normcase(str(TEST_ROOT.resolve(strict=False)))
        if test_root not in roots:
            roots.append(test_root)
    return roots


def _contains_sensitive_component(path: Path) -> bool:
    for part in path.parts:
        lowered = part.lower()
        if lowered in _SENSITIVE_NAMES or lowered.startswith(".env"):
            return True
    return False


def check_path(path_str: str) -> dict:
    """Return a structured allow/deny decision for a fully-resolved target path."""
    if not path_str or not str(path_str).strip():
        return {"safe": False, "reason": "empty_path", "path": None}
    try:
        target = Path(path_str).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        return {"safe": False, "reason": f"path_resolution_failed: {exc}", "path": None}

    if _contains_sensitive_component(target):
        return {"safe": False, "reason": "sensitive_path_component", "path": str(target)}

    normalized_target = Path(os.path.normcase(str(target)))
    for blocked_text in get_blocked_paths():
        blocked = Path(blocked_text)
        if normalized_target == blocked or _inside(normalized_target, blocked):
            return {"safe": False, "reason": "blocked_system_path", "path": str(target)}

    allowed = [Path(value) for value in get_allowed_paths()]
    if not any(normalized_target == root or _inside(normalized_target, root) for root in allowed):
        return {"safe": False, "reason": "outside_allowed_directories", "path": str(target)}

    return {"safe": True, "reason": None, "path": str(target)}


_TOOL_PATH_FIELDS = {
    "file_read": ("filepath",),
    "file_write": ("filepath",),
    "find_files": ("search_root",),
    "create_folder": ("folderpath",),
    "rename_folder": ("old_path", "new_path"),
    "delete_folder": ("folderpath",),
    "copy_folder": ("source_path", "destination_path"),
    "move_folder": ("source_path", "destination_path"),
    "list_contents": ("folderpath",),
    "compress_folder": ("folderpath",),
    "extract_zip": ("zippath", "extract_to"),
    "organize_folder": ("folderpath",),
    "convert_file_format": ("source_filepath", "destination_filepath"),
    "optimize_code": ("filepath",),
    "git_clone": ("directory",),
    "download_file": ("save_path",),
    "play_music": ("filepath",),
    "terminal_run": ("cwd",),
    "open_vscode": ("path",),
    "git_status": ("directory",),
    "semantic_code_graph": ("target_path",),
}

_AGENT_PROJECT_DEFAULTS = {
    "find_files": ("search_root",),
    "terminal_run": ("cwd",),
    "git_status": ("directory",),
}


def resolve_project_root(project_id: str = "personal") -> dict:
    """Resolve a configured project ID to one allowed canonical directory."""
    project_key = str(project_id or "personal").strip() or "personal"
    config = _load_security_config()
    configured = config.get("project_roots", {}) or {}
    value = configured.get(project_key)

    # Test agents are always rooted below their isolated runtime, even when the
    # bundled production config maps personal to the source checkout.
    if TEST_MODE and TEST_ROOT is not None and project_key == "personal":
        root = TEST_ROOT.resolve(strict=False)
    elif value in (None, ""):
        if project_key != "personal":
            return {
                "safe": False,
                "reason": "unknown_project_id",
                "project_id": project_key,
                "path": None,
            }
        if TEST_MODE and TEST_ROOT is not None:
            root = TEST_ROOT.resolve(strict=False)
        else:
            root = BASE_DIR.resolve(strict=False)
    else:
        try:
            root = _resolve_config_path(str(value))
        except (OSError, RuntimeError, ValueError) as exc:
            return {
                "safe": False,
                "reason": f"project_root_resolution_failed: {exc}",
                "project_id": project_key,
                "path": None,
            }

    decision = check_path(str(root))
    if not decision["safe"]:
        return {
            "safe": False,
            "reason": decision["reason"],
            "project_id": project_key,
            "path": decision["path"],
        }
    if not root.is_dir():
        return {
            "safe": False,
            "reason": "project_root_not_directory",
            "project_id": project_key,
            "path": str(root),
        }
    return {
        "safe": True,
        "reason": None,
        "project_id": project_key,
        "path": str(root),
    }


def resolve_agent_tool_arguments(tool_id: str, arguments: dict, project_root: str) -> dict:
    """Bind every relative agent path to its active project and reject escapes."""
    try:
        root = Path(project_root).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        return {
            "safe": False,
            "reason": f"invalid_project_root: {exc}",
            "field": None,
            "path": None,
            "arguments": dict(arguments or {}),
        }

    resolved_arguments = dict(arguments or {})
    for field in _AGENT_PROJECT_DEFAULTS.get(tool_id, ()):
        if resolved_arguments.get(field) in (None, "", "."):
            resolved_arguments[field] = str(root)

    for field in _TOOL_PATH_FIELDS.get(tool_id, ()):
        value = resolved_arguments.get(field)
        if value in (None, ""):
            continue
        candidate = Path(str(value)).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        candidate = candidate.resolve(strict=False)
        if not _inside(candidate, root) and candidate != root:
            return {
                "safe": False,
                "reason": "outside_active_project",
                "field": field,
                "path": str(candidate),
                "arguments": resolved_arguments,
            }
        decision = check_path(str(candidate))
        if not decision["safe"]:
            return {
                "safe": False,
                "reason": decision["reason"],
                "field": field,
                "path": decision["path"],
                "arguments": resolved_arguments,
            }
        resolved_arguments[field] = str(candidate)

    return {
        "safe": True,
        "reason": None,
        "field": None,
        "path": None,
        "arguments": resolved_arguments,
    }


def validate_tool_paths(tool_id: str, arguments: dict) -> dict:
    """Fail unsafe tool paths before asking the user to approve an action."""
    for field in _TOOL_PATH_FIELDS.get(tool_id, ()):
        value = arguments.get(field)
        if value in (None, ""):
            continue
        decision = check_path(str(value))
        if not decision["safe"]:
            return {
                "safe": False,
                "field": field,
                "reason": decision["reason"],
                "path": decision["path"],
            }
    return {"safe": True, "field": None, "reason": None, "path": None}


def is_path_safe(path_str: str) -> bool:
    return bool(check_path(path_str)["safe"])

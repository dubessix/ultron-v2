"""Owner routines (V2 Step D): say a name like "coding mode", Ultron runs the steps.

The steps live in one small file the owner can edit (``routines.yaml`` in
Ultron's data folder). Each step is one of Ultron's own tools plus its
arguments, so a routine can do anything Ultron can do - no special code per
routine. Steps run in order; a failed step is reported and the rest continue.

Safety: every step goes through the normal tool path (validation, path guard,
secret blocking). The owner wrote the routine and said its name, so normal
steps run without a question; level-3 steps (sudo, system folders...) are never
run from a routine - they are reported as "needs your yes" instead.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Literal, Optional
from urllib.parse import unquote, urlparse

from pydantic import BaseModel, Field

from backend.app.tools.tool_base import BaseTool

MAX_FILE_BYTES = 64 * 1024
MAX_STEPS = 20
ROUTINE_SESSION = "ultron-routine"
# A routine never starts another routine or talks to the brain's own controls.
BLOCKED_STEP_TOOLS = {"routine", "switch_mode", "use_tool", "database_restore"}

DEFAULT_ROUTINES = """\
# Ultron routines. Say the name ("coding mode") and Ultron runs the steps in order.
# A step = one of Ultron's tools + its arguments. Optional: "say" (how Ultron
# names the step), "os" (linux or windows: run only there).
# {project} = the folder you last opened in VS Code (else the last folder you used).
# Edit freely, then just say the name. Lines starting with # are notes.

coding mode:
  - say: VS Code in your project
    tool: terminal_run
    args: {command: "code .", cwd: "{project}", mode: background}
  - say: a terminal there
    os: linux
    tool: terminal_run
    args: {command: 'gnome-terminal --working-directory="{project}" || ptyxis --new-window --working-directory="{project}" || x-terminal-emulator', cwd: "{project}", mode: background}
  - say: a terminal there
    os: windows
    tool: terminal_run
    args: {command: 'start "" cmd /K', cwd: "{project}", mode: background}
  - say: lofi music
    tool: open_url
    args: {url: "https://www.youtube.com/watch?v=jfKfPfyJRdk"}
  - say: notifications quiet
    os: linux
    tool: terminal_run
    args: {command: "gsettings set org.gnome.desktop.notifications show-banners false"}

normal mode:
  - say: notifications back on
    os: linux
    tool: terminal_run
    args: {command: "gsettings set org.gnome.desktop.notifications show-banners true"}
"""


def routines_path() -> Path:
    from backend.app.runtime_paths import runtime_data_path

    return runtime_data_path("routines.yaml")


def _key(name: str) -> str:
    words = re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).split()
    return " ".join(w for w in words if w not in {"the", "start", "run", "routine", "on", "please", "karo", "chalu"})


def load_routines(path: Optional[Path] = None) -> dict[str, list[dict]]:
    """Read the owner's file (created with the defaults on first use)."""
    import yaml

    path = path or routines_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_ROUTINES, encoding="utf-8")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("routines.yaml is too big (max 64 KB).")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("routines.yaml must be a list of names, each with steps.")
    return {str(name): steps for name, steps in data.items() if isinstance(steps, list)}


def _vscode_storage_files() -> list[Path]:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return [base / app / "User" / "globalStorage" / "storage.json" for app in ("Code", "Code - Insiders", "VSCodium")]


def last_project() -> str:
    """The folder last opened in VS Code, else the folder Ultron last used, else home."""
    for storage in _vscode_storage_files():
        try:
            data = json.loads(storage.read_text(encoding="utf-8"))
            uri = (((data.get("windowsState") or {}).get("lastActiveWindow") or {}).get("folder")) or ""
            if uri.startswith("file://"):
                parsed = urlparse(uri)
                folder = unquote(parsed.path)
                if os.name == "nt" and re.match(r"^/[A-Za-z]:", folder):
                    folder = folder[1:]
                if Path(folder).is_dir():
                    return str(Path(folder))
        except (OSError, ValueError, AttributeError):
            continue
    try:
        from backend.app.core import recent_folders

        recent = recent_folders.last()
        if recent:
            return recent
    except Exception:
        pass
    return str(Path.home())


def _fill(value: Any, project: str) -> Any:
    if isinstance(value, str):
        return value.replace("{project}", project)
    if isinstance(value, dict):
        return {k: _fill(v, project) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, project) for v in value]
    return value


def _for_this_os(step: dict) -> bool:
    wanted = str(step.get("os") or "").lower().strip()
    if not wanted:
        return True
    return wanted == ("windows" if os.name == "nt" else "linux")


class RoutineArgs(BaseModel):
    name: str = Field("", max_length=80, description="Routine name as said, e.g. 'coding mode'.")
    action: Literal["run", "list"] = Field("run", description="run the routine, or list the saved routines.")


class RoutineTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="routine",
            name="Routines",
            description=("Runs one of the owner's saved routines by name, e.g. 'coding mode' (VS Code in the last "
                         "project, a terminal there, lofi, quiet notifications) - steps from routines.yaml, in "
                         "order. action=list shows them."),
            category="system",
            tags=["routine", "mode", "coding mode", "protocol", "setup"],
            permission_level=1,
            args_model=RoutineArgs,
            usage_examples=["routine(name='coding mode')", "routine(action='list')"],
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        try:
            routines = load_routines()
        except Exception as exc:
            return {"success": False, "data": {"file": str(routines_path())},
                    "error": f"Could not read routines.yaml: {str(exc)[:200]}"}
        names = sorted(routines)
        if kwargs.get("action") == "list":
            return {"success": True, "error": None,
                    "data": {"routines": {n: len(routines[n]) for n in names}, "file": str(routines_path())}}

        wanted = _key(kwargs.get("name") or "")
        match = next((n for n in names if _key(n) == wanted), None)
        if match is None and wanted:
            match = next((n for n in names if wanted in _key(n) or _key(n) in wanted), None)
        if match is None:
            return {"success": False, "data": {"routines": names, "file": str(routines_path())},
                    "error": f"No routine called '{kwargs.get('name')}'. Saved: {', '.join(names) or 'none'}."}
        return await self._run(match, routines[match])

    async def _run(self, name: str, steps: list) -> Dict[str, Any]:
        from backend.app.core import stop_signal
        from backend.app.tools.tool_registry import ToolRegistry

        registry = ToolRegistry()
        project = last_project()
        done: list[str] = []
        failed: list[dict] = []
        needs_yes: list[str] = []
        stopped = False
        runnable = [s for s in steps if isinstance(s, dict) and _for_this_os(s)][:MAX_STEPS]
        for number, step in enumerate(runnable, 1):
            if stop_signal.requested():
                stopped = True
                break
            tool_id = str(step.get("tool") or "").strip()
            label = str(step.get("say") or tool_id or f"step {number}")[:80]
            if not tool_id or tool_id in BLOCKED_STEP_TOOLS or registry.get_tool(tool_id) is None:
                failed.append({"step": label, "error": f"'{tool_id}' is not a tool Ultron can use in a routine."})
                continue
            args = _fill(step.get("args") or {}, project)
            if not isinstance(args, dict):
                failed.append({"step": label, "error": "args must be a list of name: value."})
                continue
            try:
                result = await registry.execute_tool(tool_id=tool_id, args=args, session_id=ROUTINE_SESSION,
                                                     owner_approved=True, max_retries=0)
            except Exception as exc:  # one broken step never stops the rest
                result = {"success": False, "error": str(exc)}
            if result.get("status") == "PENDING_CONFIRMATION":
                from backend.app.security.pending_actions import get_pending_action_registry

                try:  # never leave a question hanging that nobody will answer
                    get_pending_action_registry().claim(result.get("confirmation_token"), ROUTINE_SESSION, cancel=True)
                except Exception:
                    pass
                needs_yes.append(label)
            elif result.get("success"):
                done.append(label)
            else:
                failed.append({"step": label, "error": str(result.get("error") or "failed")[:200]})
        data = {"routine": name, "project": project, "done": done, "failed": failed}
        if needs_yes:
            data["needs_your_yes"] = needs_yes
        if stopped:
            data["stopped"] = "You said stop, so the rest was not started."
        if not runnable:
            return {"success": False, "data": data, "error": f"'{name}' has no steps for this PC."}
        return {"success": bool(done), "data": data,
                "error": None if done else "No step of the routine worked: " + "; ".join(f["error"] for f in failed)[:300]}

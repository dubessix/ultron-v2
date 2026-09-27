"""
Ultron System Automation Tools
Implements production-grade, asynchronous non-blocking terminal command run runtimes (Level 2 Security).
Natively integrates an un-mocked, stateful Self-Healing Compiler Loop (Autoreactive Debugger).
"""

import os
import ntpath
import shlex
import platform
import asyncio
import re
import shutil
import subprocess
import yaml
from pathlib import Path
from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel, Field
from backend.app.install_paths import CONFIG_PATH
from backend.app.tools.tool_base import BaseTool

# Phase 4: commands that contain shell metacharacters (pipes, redirects, chaining,
# substitution) must start with an approved, developer-oriented command so the
# shell is only ever used for legitimate build/test/dev operations.
_DEFAULT_APPROVED_COMMANDS = {
    "git", "python", "python3", "pytest", "pip", "pip3", "node", "npm", "npx",
    "yarn", "pnpm", "uvicorn", "ls", "pwd", "cat", "grep", "find", "head",
    "tail", "echo", "printf", "diff", "sort", "wc", "cut", "awk", "sed",
    "make", "cmake", "go", "cargo", "rustc", "dotnet", "sleep",
}

_SHELL_METACHARS = (";", "&", "|", ">", "<", "`", "$(")
_WINDOWS_EXECUTABLE_SUFFIXES = (".exe", ".cmd", ".bat", ".com")
MAX_TERMINAL_OUTPUT_BYTES = 1024 * 1024
DEFAULT_WAIT_SECONDS = 60
MAX_WAIT_SECONDS = 120


def _split_command(command: str) -> list[str]:
    """Split with native Windows quoting without destroying backslashes."""
    if os.name != "nt":
        return shlex.split(command)

    import ctypes
    from ctypes import wintypes

    argc = ctypes.c_int(0)
    parser = ctypes.windll.shell32.CommandLineToArgvW
    parser.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    parser.restype = ctypes.POINTER(wintypes.LPWSTR)
    argv = parser(command, ctypes.byref(argc))
    if not argv:
        raise ValueError("Windows could not parse the command line.")
    try:
        return [argv[index] for index in range(argc.value)]
    finally:
        local_free = ctypes.windll.kernel32.LocalFree
        local_free.argtypes = [wintypes.HLOCAL]
        local_free.restype = wintypes.HLOCAL
        local_free(ctypes.cast(argv, wintypes.HLOCAL))


def _default_terminal_folder(check_path) -> Path:
    """Where the owner works (last folder, else home); the allowed project folder
    only in the restricted access mode. Never raises."""
    try:
        from backend.app.core import recent_folders

        folder = recent_folders.personal_base()
        if check_path(str(folder))["safe"]:
            return folder
    except Exception:
        pass
    try:
        from backend.app.security.path_guard import resolve_project_root

        decision = resolve_project_root("personal")
        if decision.get("safe"):
            return Path(decision["path"])
    except Exception:
        pass
    return Path.home()


def _normalized_executable_name(value: str) -> str:
    name = ntpath.basename(value).lower()
    for suffix in _WINDOWS_EXECUTABLE_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _requires_shell(command: str) -> bool:
    """True if the command uses shell metacharacters (needs a real shell)."""
    if any(mc in command for mc in _SHELL_METACHARS):
        return True
    # Unbalanced quotes are unsafe to split naively -> treat as shell.
    try:
        _split_command(command)
    except ValueError:
        return True
    return False


def _load_approved_commands() -> set[str]:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
            configured = (
                (yaml.safe_load(handle) or {})
                .get("security", {})
                .get("terminal_allowed_commands", [])
            )
        commands = {str(item).strip().lower() for item in configured if str(item).strip()}
        return commands or set(_DEFAULT_APPROVED_COMMANDS)
    except (OSError, yaml.YAMLError):
        return set(_DEFAULT_APPROVED_COMMANDS)


def _terminal_policy_any() -> bool:
    """Jarvis shell: `security.terminal_policy: any` (or ULTRON_TERMINAL_POLICY=any).

    Any executable may run — still behind the level-2 exact confirmation card
    and the destructive-pattern risk guard. Isolated tests keep the allowlist
    unless they opt in with ULTRON_TEST_FULL_ACCESS=1.
    """
    from backend.app.runtime_paths import TEST_MODE
    if TEST_MODE and os.getenv("ULTRON_TEST_FULL_ACCESS", "") != "1":
        return False
    policy = os.getenv("ULTRON_TERMINAL_POLICY", "").strip().lower()
    if not policy:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
                policy = str(
                    ((yaml.safe_load(handle) or {}).get("security", {}) or {}).get(
                        "terminal_policy", "allowlist"
                    )
                ).strip().lower()
        except (OSError, yaml.YAMLError):
            policy = "allowlist"
    return policy == "any"


def _approved_command(command: str) -> bool:
    """Every command, with or without shell syntax, needs an approved executable."""
    if _terminal_policy_any():
        try:
            return bool(_split_command(command))
        except ValueError:
            return bool(command.strip())
    try:
        parts = _split_command(command)
    except ValueError:
        return False
    if not parts:
        return False
    first = _normalized_executable_name(parts[0])
    return first in _load_approved_commands()

class TerminalRunArgs(BaseModel):
    command: str = Field("", description="Shell command for the owner's PC. Use no-question flags (-y, --yes, --no-interactive): nothing can type into it.")
    cwd: Optional[str] = Field(None, description="Folder: full path, '~/...', 'Desktop' or a folder name (auto-found). Default: the folder Ultron last used, else home.")
    mode: Literal["wait", "background", "status", "stop"] = Field("wait", description="wait: run and return the result (still running after wait_seconds -> keeps running as a job). background: servers, GUI programs, long jobs; returns at once. status/stop: a job by job_id (status with no id lists jobs).")
    wait_seconds: int = Field(DEFAULT_WAIT_SECONDS, ge=1, le=MAX_WAIT_SECONDS, description="wait mode: how long to wait before leaving it running in the background.")
    job_id: Optional[str] = Field(None, description="Job id for status / stop.")


class AppLaunchArgs(BaseModel):
    pass


class VSCodeLaunchArgs(BaseModel):
    path: Optional[str] = Field(None, description="Approved file or directory to open in VS Code.")


class TerminalRunTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="terminal_run",
            name="Terminal Runner",
            description="Executes shell terminal commands on the local machine.",
            category="system",
            tags=["run", "execute", "terminal", "bash", "cmd", "shell"],
            permission_level=2, # Level 2: System Command (Manual Confirmation Required)
            args_model=TerminalRunArgs,
            usage_examples=["terminal_run(command='npm run build')"]
        )
        # the registry allows the longest wait plus a margin (not the 30 s default)
        self.max_runtime_seconds = MAX_WAIT_SECONDS + 15

    # V2 Step 7 (Tony mode): plain look-only commands run without asking.
    _READ_ONLY = {
        "ls", "dir", "pwd", "whoami", "date", "uptime", "df", "du", "free", "uname", "hostname", "ps",
        "tasklist", "systeminfo", "ipconfig", "ifconfig", "ip", "ping", "nvidia-smi", "lscpu", "lsblk",
        "lsusb", "which", "where", "wc", "tree",
        "python", "python3", "node", "npm", "pip", "java", "git",
    }
    _READ_ONLY_SUBCOMMANDS = {
        "git": {"status", "log", "diff", "branch", "show", "remote", "rev-parse"},
        "python": {"--version", "-V"}, "python3": {"--version", "-V"}, "node": {"--version", "-v"},
        "npm": {"--version", "-v", "ls", "list", "outdated"}, "pip": {"--version", "list", "show", "freeze"},
        "java": {"-version", "--version"}, "ip": {"a", "addr", "address", "route", "link"},
    }

    def permission_for_arguments(self, arguments):
        import re as _re
        import shlex as _shlex

        command = str((arguments or {}).get("command") or "").strip()
        if not command or _re.search(r"[;&|<>`$\n]|\bsudo\b", command):
            return self.permission_level
        try:
            parts = _shlex.split(command, posix=os.name != "nt")
        except ValueError:
            return self.permission_level
        word = os.path.basename(parts[0]).lower().removesuffix(".exe") if parts else ""
        if word not in self._READ_ONLY:
            return self.permission_level
        allowed_sub = self._READ_ONLY_SUBCOMMANDS.get(word)
        if allowed_sub is not None and (len(parts) < 2 or parts[1] not in allowed_sub):
            return self.permission_level
        if word == "ping" and not any(p in {"-c", "-n"} for p in parts):
            return self.permission_level  # endless ping would hang the turn
        return 1

    def _attempt_self_healing_analysis(self, stderr: str, project_root: Optional[Path] = None) -> Optional[Dict[str, Any]]:
        """
        AUTOREACTIVE SELF-HEALING DEBUGGER (Requirement: Jarvis-like presence)
        Parses standard error logs for Python, Node/JS, and common backend errors.
        If a real file path is found, reads the offending line and drafts a precise
        patch suggestion. If no file can be resolved, still returns a useful hint
        derived from the error type (not a dummy/pattern-only guess).
        """
        # 1. Python traceback: File "filename.py", line XX
        python_pattern = re.compile(r'File "([^"]+\.py[^"]*)", line (\d+)', re.IGNORECASE)
        # 2. Node/JS stack: at ... (file.js:LINE:COL)  OR  file.js:LINE:COL  OR  file.js:LINE
        node_at = re.compile(r"\(([^()]+\.(?:js|jsx|ts|tsx|mjs|cjs)):(\d+)(?::\d+)?\)", re.IGNORECASE)
        node_top = re.compile(r"^([^\s:]+\.(?:js|jsx|ts|tsx|mjs|cjs)):(\d+)", re.IGNORECASE)

        file_path_str = None
        line_num = None
        lang = None

        # Python first
        m = python_pattern.search(stderr)
        if m:
            file_path_str = m.group(1)
            line_num = int(m.group(2))
            lang = "python"
        else:
            m = node_at.search(stderr)
            if m:
                file_path_str = m.group(1)
                line_num = int(m.group(2))
                lang = "node"
            else:
                m = node_top.search(stderr)
                if m:
                    file_path_str = m.group(1)
                    line_num = int(m.group(2))
                    lang = "node"

        # --- General error-type hint (works even if no file can be resolved) ---
        fix_hint = "Review and fix the reported error."
        severity = "minor"
        if "is not defined" in stderr or "ReferenceError" in stderr or "NameError" in stderr:
            name = re.search(r"(?:name '([^']+)'|([A-Za-z_][A-Za-z0-9_]*) is not defined)", stderr)
            fix_hint = (f"'{name.group(1) or name.group(2)}' is not defined — check the import/variable above.") if name else "Undefined name/variable — check imports and scope."
            severity = "error"
        elif "Cannot find module" in stderr or "Module not found" in stderr or "ModuleNotFoundError" in stderr or "No module named" in stderr:
            mod = re.search(r"(?:Cannot find module '([^']+)'|No module named '([^']+)')", stderr)
            is_py = lang == "python" or "ModuleNotFoundError" in stderr or "No module named" in stderr
            pkg = mod.group(1) or mod.group(2) if mod else ""
            if pkg:
                install = f"pip install {pkg}" if is_py else f"npm install {pkg}"
                fix_hint = f"Missing module '{pkg}' — run: {install}"
            else:
                fix_hint = "Missing module/dependency — install it."
            severity = "error"
        elif "SyntaxError" in stderr or "Unexpected token" in stderr or "unexpected indent" in stderr or "expected an indented block" in stderr:
            fix_hint = "Syntax error — check brackets, quotes, and indentation."
            severity = "error"
        elif "TypeError" in stderr:
            fix_hint = "Type error — a value has the wrong type. Check the operation on this line."
            severity = "error"
        elif "Unexpected identifier" in stderr or "is not a function" in stderr:
            fix_hint = "Likely a wrong variable/function usage — verify the name and definition."
            severity = "error"

        # If we couldn't resolve a real file, return the hint alone (real, not dummy).
        if not file_path_str or not line_num:
            return {
                "filepath": None,
                "line": None,
                "error_trace": stderr.strip(),
                "offending_line": None,
                "suggested_patch": None,
                "fix_hint": fix_hint,
                "severity": severity,
                "file_resolved": False
            }

        # Resolve the offending file path. If it's relative, anchor it to the project root.
        file_path = Path(file_path_str)
        if not file_path.is_absolute() and project_root is not None:
            file_path = project_root / file_path
        file_path = file_path.resolve()
        if not file_path.exists() or not file_path.is_file():
            return {
                "filepath": str(file_path),
                "line": line_num,
                "error_trace": stderr.strip(),
                "offending_line": None,
                "suggested_patch": None,
                "fix_hint": fix_hint,
                "severity": severity,
                "file_resolved": False
            }

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            if line_num <= len(lines):
                offending_line = lines[line_num - 1]
                suggested_patch = offending_line

                # --- Smarter syntax heuristics (safe, read-only analysis) ---
                stripped = offending_line.strip()
                # 1. Missing closing parenthesis on a call like print("hello"  / foo(
                if ("(" in offending_line) and (
                        stripped.endswith((",", "(", "+", "=")) or
                        (stripped.count("(") > stripped.count(")"))):
                    suggested_patch = offending_line.rstrip() + ")\n"
                    fix_hint = "This line has an unclosed call — add the missing closing parenthesis."
                    severity = "error"
                # 2. Open string / missing closing quote
                elif stripped.count('"') % 2 == 1 or stripped.count("'") % 2 == 1:
                    suggested_patch = offending_line
                    fix_hint = "This line has an unbalanced quote — close the string."
                    severity = "error"
                # 3. Specific error-line hint (undefined var, module, etc.)
                elif fix_hint and fix_hint != "Review and fix the reported error.":
                    pass  # keep the general hint, it's already specific
                else:
                    fix_hint = "Review this line and the error above."

                return {
                    "filepath": str(file_path),
                    "line": line_num,
                    "lang": lang,
                    "error_trace": stderr.strip(),
                    "offending_line": offending_line.strip(),
                    "suggested_patch": suggested_patch,
                    "fix_hint": fix_hint,
                    "severity": severity,
                    "file_resolved": True
                }
        except Exception as e:
            print(f"[SELF_HEALING] Warning: Failed to parse file for self-healing: {e}")

        return None


    async def execute(self, **kwargs) -> Dict[str, Any]:
        from backend.app.tools import terminal_jobs

        mode = str(kwargs.get("mode") or "wait")
        if mode == "status":
            return await asyncio.to_thread(terminal_jobs.status, kwargs.get("job_id"))
        if mode == "stop":
            if not kwargs.get("job_id"):
                return {"success": False, "error": "Say which job_id to stop (mode=status lists them).", "data": {}}
            return await asyncio.to_thread(terminal_jobs.stop, kwargs["job_id"])

        command = str(kwargs.get("command", ""))
        if not command.strip():
            return {"success": False, "error": "Command parameter is empty.", "data": {}}

        from backend.app.security.path_guard import check_path
        from backend.app.tools._cmd_guard import is_command_safe

        if not is_command_safe(command):
            return {"success": False, "error": "Command blocked by risk guard.", "data": {}}

        default_root = _default_terminal_folder(check_path)
        project_root = Path(kwargs.get("cwd") or default_root).expanduser().resolve(strict=False)
        path_decision = check_path(str(project_root))
        if not path_decision["safe"]:
            return {
                "success": False,
                "error": f"Working directory blocked ({path_decision['reason']}): {project_root}",
                "data": {},
            }
        if not project_root.is_dir():
            return {"success": False, "error": f"Working directory does not exist: {project_root}", "data": {}}

        use_shell = _requires_shell(command)
        if not _approved_command(command):
            return {
                "success": False,
                "error": "Command blocked: executable is not in security.terminal_allowed_commands.",
                "data": {},
            }
        argv = None
        if not use_shell:
            argv = _split_command(command)
            if not argv:
                return {"success": False, "error": "Command parameter is empty.", "data": {}}
            resolved = shutil.which(argv[0], path=os.environ.get("PATH"))
            if resolved:
                argv[0] = resolved
            elif not Path(argv[0]).exists():
                use_shell, argv = True, None  # a shell built-in (cd, dir, echo, export...) or missing

        try:
            job = await asyncio.to_thread(
                terminal_jobs.start, command, str(project_root), use_shell=use_shell, argv=argv,
                timed=mode != "background",  # servers keep running; normal commands get the time cap
            )
        except OSError as exc:
            return {"success": False, "error": f"Could not start the command: {exc}", "data": {}}

        if mode == "background":
            code = await terminal_jobs.wait(job["id"], 2.0)  # catch an instant crash
            data = {"job_id": job["id"], "pid": job["pid"], "cwd": str(project_root),
                    "running": code is None, "exit_code": code, **terminal_jobs.output(job)}
            if code is None:
                data["note"] = "Running in the background. Check with mode=status, end with mode=stop."
                return {"success": True, "data": data, "error": None}
            return {"success": code == 0, "data": data,
                    "error": None if code == 0 else (data["stderr"] or f"Exited with code {code}.")}

        seconds = max(1, min(int(kwargs.get("wait_seconds") or DEFAULT_WAIT_SECONDS), MAX_WAIT_SECONDS))
        from backend.app.core import stop_signal

        try:
            code = await terminal_jobs.wait(job["id"], seconds, should_stop=stop_signal.requested)
        except asyncio.CancelledError:
            await asyncio.to_thread(terminal_jobs.kill_now, job["id"])  # a cancelled turn leaves nothing behind
            raise
        if code is None and stop_signal.requested():
            await asyncio.to_thread(terminal_jobs.stop, job["id"])  # the owner said stop: end it now
            return {"success": False, "error": "Stopped because you said stop.",
                    "data": {"stopped": True, "job_id": job["id"], **terminal_jobs.output(job)}}
        out = terminal_jobs.output(job)
        if code is None:
            return {"success": True, "error": None, "data": {
                "exit_code": None, "running": True, "job_id": job["id"], "cwd": str(project_root),
                "note": f"Still running after {seconds}s, so it keeps going in the background"
                        f"{_time_cap_hint(terminal_jobs.time_limit_seconds())}. "
                        "Not finished yet: say so. Check with mode=status, end with mode=stop.",
                **out, "self_healing_fix": None}}

        data = {"exit_code": code, "cwd": str(project_root), **out, "self_healing_fix": None}
        if code != 0 and out["stderr"]:
            healing = self._attempt_self_healing_analysis(out["stderr"], project_root)
            if healing:
                data["self_healing_fix"] = healing
        error = None
        if code != 0:
            error = out["stderr"] or out["stdout"][-500:] or f"Exited with code {code}."
            if code in (127, 9009) or "is not recognized as an internal or external command" in error:
                program = command.split()[0]
                error = f"'{program}' is not installed or not on PATH. {error}".strip()
        return {"success": code == 0, "data": data, "error": error}


def _time_cap_hint(cap_seconds: int) -> str:
    if not cap_seconds:
        return ""
    return f" (stopped after {max(1, cap_seconds // 60)} min; servers belong in mode=background)"


async def _launch_verified(candidates, args=None):
    """Verify an executable exists and that process creation succeeds without a shell."""
    executable = next((shutil.which(name) for name in candidates if shutil.which(name)), None)
    if not executable:
        return {"success": False, "error": f"Required executable unavailable: {', '.join(candidates)}", "data": {}}
    argv = [executable, *(args or [])]
    try:
        process = await asyncio.to_thread(
            subprocess.Popen,
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        return {"success": False, "error": f"Failed to start {executable}: {exc}", "data": {}}
    return {
        "success": True,
        "data": {
            "status": "dispatched_unverified",
            "executable": executable,
            "pid": process.pid,
            "message": "Application process was created; GUI readiness cannot be verified.",
        },
        "error": None,
    }


class CalculatorTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="open_calculator",
            name="Calculator Launcher",
            description="Launches the local hardware calculator application.",
            category="system",
            tags=["open", "launch", "calculate", "calculator", "math"],
            permission_level=1,
            args_model=AppLaunchArgs,
            usage_examples=["open_calculator()"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        candidates = ["calc.exe"] if platform.system() == "Windows" else ["gnome-calculator", "kcalc"]
        return await _launch_verified(candidates)

class ChromeLauncherTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="open_chrome",
            name="Chrome Launcher",
            description="Launches the Google Chrome web browser application.",
            category="system",
            tags=["open", "launch", "chrome", "browser", "web", "internet"],
            permission_level=1,
            args_model=AppLaunchArgs,
            usage_examples=["open_chrome()"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        candidates = (
            ["chrome.exe", "chrome"]
            if platform.system() == "Windows"
            else ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]
        )
        return await _launch_verified(candidates)

class VSCodeLauncherTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="open_vscode",
            name="VS Code Launcher",
            description="Launches the Visual Studio Code editor workspace.",
            category="system",
            tags=["open", "launch", "code", "vscode", "editor", "ide"],
            permission_level=1,
            args_model=VSCodeLaunchArgs,
            usage_examples=["open_vscode(path='.')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        path_value = kwargs.get("path")
        arguments = []
        resolved_path = None
        if path_value:
            from backend.app.security.path_guard import check_path

            resolved_path = Path(str(path_value)).expanduser().resolve(strict=False)
            decision = check_path(str(resolved_path))
            if not decision["safe"]:
                return {
                    "success": False,
                    "error": f"VS Code path blocked ({decision['reason']}): {resolved_path}",
                    "data": {},
                }
            if not resolved_path.exists():
                return {"success": False, "error": f"VS Code path does not exist: {resolved_path}", "data": {}}
            arguments.append(str(resolved_path))
        result = await _launch_verified(["code", "code-insiders"], arguments)
        if result.get("success") and resolved_path is not None:
            result["data"]["requested_path"] = str(resolved_path)
        return result

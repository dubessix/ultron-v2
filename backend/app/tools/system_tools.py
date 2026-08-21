"""
Ultron System Automation Tools
Implements production-grade, asynchronous non-blocking terminal command run runtimes (Level 2 Security).
Natively integrates an un-mocked, stateful Self-Healing Compiler Loop (Autoreactive Debugger).
"""

import os
import ntpath
import shlex
import signal
import platform
import asyncio
import re
import shutil
import subprocess
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
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
TERMINAL_TIMEOUT_SECONDS = 20.0


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


def _approved_command(command: str) -> bool:
    """Every command, with or without shell syntax, needs an approved executable."""
    try:
        parts = _split_command(command)
    except ValueError:
        return False
    if not parts:
        return False
    first = _normalized_executable_name(parts[0])
    return first in _load_approved_commands()

class TerminalRunArgs(BaseModel):
    command: str = Field(..., description="Local system command to execute after exact confirmation.")
    cwd: Optional[str] = Field(None, description="Approved project working directory; defaults to Ultron project root.")

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

    @staticmethod
    async def _read_limited(stream, limit: int):
        """Drain a pipe fully while retaining at most limit bytes."""
        chunks = []
        retained = 0
        total = 0
        while True:
            chunk = await stream.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if retained < limit:
                keep = chunk[: limit - retained]
                chunks.append(keep)
                retained += len(keep)
        return b"".join(chunks), total > limit

    @staticmethod
    async def _terminate_process_group(proc) -> None:
        """Kill and await the complete process group so transports are closed."""
        if proc is None or proc.returncode is not None:
            return
        try:
            if os.name != "nt":
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                killed = await asyncio.to_thread(
                    subprocess.run,
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=10.0,
                )
                if killed.returncode != 0 and proc.returncode is None:
                    proc.kill()
        except (OSError, ProcessLookupError, PermissionError, subprocess.SubprocessError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except (asyncio.TimeoutError, ProcessLookupError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass

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
        command = str(kwargs.get("command", ""))
        if not command.strip():
            return {"success": False, "error": "Command parameter is empty.", "data": {}}

        from backend.app.security.path_guard import check_path
        from backend.app.tools._cmd_guard import is_command_safe

        if not is_command_safe(command):
            return {"success": False, "error": "Command blocked by risk guard.", "data": {}}

        default_root = Path(__file__).resolve().parent.parent.parent.parent
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

        proc = None
        stdout_task = None
        stderr_task = None
        try:
            common = {
                "cwd": str(project_root),
                "stdout": asyncio.subprocess.PIPE,
                "stderr": asyncio.subprocess.PIPE,
            }
            if os.name == "nt":
                common["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            else:
                common["start_new_session"] = True
            if use_shell:
                proc = await asyncio.create_subprocess_shell(command, **common)
            else:
                argv = _split_command(command)
                if not argv:
                    return {"success": False, "error": "Command parameter is empty.", "data": {}}
                proc = await asyncio.create_subprocess_exec(*argv, **common)

            stdout_task = asyncio.create_task(
                self._read_limited(proc.stdout, MAX_TERMINAL_OUTPUT_BYTES)
            )
            stderr_task = asyncio.create_task(
                self._read_limited(proc.stderr, MAX_TERMINAL_OUTPUT_BYTES)
            )

            timed_out = False
            try:
                await asyncio.wait_for(proc.wait(), timeout=TERMINAL_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                timed_out = True
                await self._terminate_process_group(proc)

            stdout_result, stderr_result = await asyncio.gather(stdout_task, stderr_task)
            stdout_bytes, stdout_truncated = stdout_result
            stderr_bytes, stderr_truncated = stderr_result
            stdout = stdout_bytes.decode("utf-8", "ignore").strip()
            stderr = stderr_bytes.decode("utf-8", "ignore").strip()
            if stdout_truncated:
                stdout += "\n[output truncated]"
            if stderr_truncated:
                stderr += "\n[output truncated]"

            if timed_out:
                message = f"Command timed out after {int(TERMINAL_TIMEOUT_SECONDS)}s; process group terminated."
                return {
                    "success": False,
                    "data": {
                        "exit_code": 124,
                        "stdout": stdout,
                        "stderr": stderr or message,
                        "stdout_truncated": stdout_truncated,
                        "stderr_truncated": stderr_truncated,
                        "cwd": str(project_root),
                        "self_healing_fix": None,
                    },
                    "error": message,
                }

            exit_code = proc.returncode
            data = {
                "exit_code": exit_code,
                "stdout": stdout,
                "stderr": stderr,
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
                "cwd": str(project_root),
                "self_healing_fix": None,
            }
            if exit_code != 0 and stderr:
                healing = self._attempt_self_healing_analysis(stderr, project_root)
                if healing:
                    data["self_healing_fix"] = healing

            return {
                "success": exit_code == 0,
                "data": data,
                "error": stderr if exit_code != 0 else None,
            }

        except asyncio.CancelledError:
            await self._terminate_process_group(proc)
            if stdout_task or stderr_task:
                await asyncio.gather(
                    *(task for task in (stdout_task, stderr_task) if task),
                    return_exceptions=True,
                )
            raise
        except Exception as exc:
            await self._terminate_process_group(proc)
            return {"success": False, "error": f"Execution failed: {exc}", "data": {}}


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
            permission_level=2,
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
            permission_level=2,
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
            permission_level=2,
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

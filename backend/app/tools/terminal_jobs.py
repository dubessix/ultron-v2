"""Terminal jobs: one general shell hand for any job (IRIS/Stonic style).

Every command Ultron runs becomes a small "job":
  * output goes to two log files (never into RAM), stdin is closed and the usual
    "no questions" variables are set, so nothing can hang waiting for typing;
  * wait mode polls until the job ends or the wait limit passes - then the job
    simply keeps running in the background (never killed for being slow);
  * background mode returns at once (servers, GUI programs, long installs);
  * status / stop work by job id, and stop kills the whole process tree;
  * the AI sees only the head + tail of long output; the full log stays on disk.

Light for an old PC: no threads, no pipes to drain, a 0.25 s poll while
waiting, old logs pruned, huge logs trimmed. Nothing here ever raises into the
agent loop - callers get plain dicts.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

IS_WINDOWS = os.name == "nt"
HEAD_CHARS = 1500
TAIL_CHARS = 3000
STDERR_TAIL_CHARS = 2500
MAX_JOBS_KEPT = 25
LOG_KEEP_SECONDS = 2 * 86400
MAX_LOG_BYTES = 20 * 1024 * 1024
TRIMMED_KEEP_BYTES = 256 * 1024

# Programs read these and stop asking questions.
NON_INTERACTIVE_ENV = {
    "CI": "1",
    "DEBIAN_FRONTEND": "noninteractive",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "",
    "PIP_NO_INPUT": "1",
    "npm_config_yes": "true",
    "NPM_CONFIG_FUND": "false",
    "NPM_CONFIG_UPDATE_NOTIFIER": "false",
    "PYTHONUNBUFFERED": "1",
    "PAGER": "cat",
    "GIT_PAGER": "cat",
}

_lock = threading.Lock()
_procs: dict[str, subprocess.Popen] = {}  # live handles for jobs started by this process


def _dir() -> Path:
    from backend.app.runtime_paths import runtime_data_path

    folder = runtime_data_path("terminal_jobs")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _index_path() -> Path:
    return _dir() / "jobs.json"


def _load() -> dict[str, dict]:
    try:
        data = json.loads(_index_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(jobs: dict[str, dict]) -> None:
    try:
        path = _index_path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(jobs, indent=0), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def _create_time(pid: int) -> Optional[float]:
    try:
        import psutil

        return psutil.Process(pid).create_time()
    except Exception:
        return None


def start(command: str, cwd: str, *, use_shell: bool, argv: Optional[list[str]] = None) -> dict:
    """Start a job detached from Ultron's own process; returns its record."""
    prune()
    job_id = uuid.uuid4().hex[:8]
    folder = _dir()
    out_path, err_path = folder / f"{job_id}.out.log", folder / f"{job_id}.err.log"
    env = {**os.environ, **NON_INTERACTIVE_ENV}
    kwargs: dict[str, Any] = {"cwd": cwd, "stdin": subprocess.DEVNULL, "env": env}
    if IS_WINDOWS:
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "CREATE_NO_WINDOW", 0
        )
    else:
        kwargs["start_new_session"] = True
    with open(out_path, "ab") as out, open(err_path, "ab") as err:
        if use_shell:
            proc = subprocess.Popen(command, shell=True, stdout=out, stderr=err, **kwargs)  # nosec B602 - owner shell, risk-guarded + approval-gated
        else:
            proc = subprocess.Popen(argv or [], stdout=out, stderr=err, **kwargs)  # noqa: S603 - argv list
    record = {
        "id": job_id, "pid": proc.pid, "command": command[:300], "cwd": cwd,
        "started": time.time(), "create_time": _create_time(proc.pid),
        "out": str(out_path), "err": str(err_path), "exit_code": None, "ended": None,
    }
    with _lock:
        _procs[job_id] = proc
        jobs = _load()
        jobs[job_id] = record
        _save(jobs)
    return record


def _poll(job_id: str) -> Optional[int]:
    """Exit code if the job ended, else None (works for jobs from earlier runs too)."""
    proc = _procs.get(job_id)
    if proc is not None:
        return proc.poll()
    record = _load().get(job_id) or {}
    if record.get("exit_code") is not None:
        return record["exit_code"]
    return None if _alive(record) else -1  # ended while Ultron was away: code unknown


def _alive(record: dict) -> bool:
    pid = record.get("pid")
    if not pid:
        return False
    try:
        import psutil

        proc = psutil.Process(int(pid))
        created = record.get("create_time")
        if created and abs(proc.create_time() - float(created)) > 1.0:
            return False  # the PID was reused by some other program
        return proc.status() != psutil.STATUS_ZOMBIE
    except Exception:
        return False


def _mark_ended(job_id: str, code: int) -> None:
    with _lock:
        jobs = _load()
        if job_id in jobs and jobs[job_id].get("exit_code") is None:
            jobs[job_id].update(exit_code=code, ended=time.time())
            _save(jobs)
        _procs.pop(job_id, None)


async def wait(job_id: str, seconds: float) -> Optional[int]:
    """Wait up to `seconds` for the job; exit code, or None if still running."""
    deadline = time.monotonic() + max(0.0, seconds)
    while True:
        code = _poll(job_id)
        if code is not None:
            _mark_ended(job_id, code)
            return code
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(0.25)


def _read_tail(path: str, limit: int) -> tuple[str, int]:
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - limit))
            return handle.read().decode("utf-8", "ignore"), size
    except OSError:
        return "", 0


def _read_head(path: str, limit: int) -> str:
    try:
        with open(path, "rb") as handle:
            return handle.read(limit).decode("utf-8", "ignore")
    except OSError:
        return ""


def output(record: dict) -> dict:
    """Head + tail of stdout and the tail of stderr - what the AI needs, not more."""
    tail, size = _read_tail(record["out"], TAIL_CHARS * 2)
    if size <= HEAD_CHARS + TAIL_CHARS:
        stdout, cut = tail, False
    else:
        head = _read_head(record["out"], HEAD_CHARS)
        stdout = f"{head.rstrip()}\n... [middle skipped; full log: {record['out']}] ...\n{tail[-TAIL_CHARS:].lstrip()}"
        cut = True
    stderr, err_size = _read_tail(record["err"], STDERR_TAIL_CHARS)
    return {
        "stdout": stdout.strip(),
        "stderr": stderr.strip(),
        "stdout_truncated": cut,
        "stderr_truncated": err_size > STDERR_TAIL_CHARS,
        "log": record["out"],
    }


def _kill_tree(pid: int) -> None:
    try:
        import psutil

        parent = psutil.Process(pid)
        family = parent.children(recursive=True) + [parent]
        for proc in family:
            try:
                proc.kill()
            except psutil.Error:
                pass
        psutil.wait_procs(family, timeout=5)
    except Exception:
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], stdout=subprocess.DEVNULL,  # noqa: S603,S607
                           stderr=subprocess.DEVNULL, check=False, timeout=10)


def stop(job_id: str) -> dict:
    """Stop one job and everything it started."""
    record = _load().get(str(job_id or "").strip())
    if not record:
        return {"success": False, "error": f"No job with id '{job_id}'. Use mode=status to see jobs.", "data": {}}
    if _poll(record["id"]) is not None:
        return {"success": True, "error": None, "data": {"job_id": record["id"], "already_ended": True}}
    proc = _procs.get(record["id"])
    if proc is not None or _alive(record):
        _kill_tree(int(record["pid"]))
    if proc is not None:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    ended = _poll(record["id"]) is not None or not _alive(record)
    if ended:
        _mark_ended(record["id"], -9)
    return {"success": ended, "error": None if ended else "The job did not stop.",
            "data": {"job_id": record["id"], "stopped": ended, "command": record["command"]}}


def status(job_id: Optional[str] = None) -> dict:
    """One job in detail, or a short list of recent jobs."""
    jobs = _load()
    if job_id:
        record = jobs.get(str(job_id).strip())
        if not record:
            return {"success": False, "error": f"No job with id '{job_id}'.", "data": {}}
        code = _poll(record["id"])
        if code is not None:
            _mark_ended(record["id"], code)
        return {"success": True, "error": None, "data": {
            "job_id": record["id"], "command": record["command"], "cwd": record["cwd"],
            "running": code is None, "exit_code": code,
            "seconds": int((record.get("ended") or time.time()) - record["started"]),
            **output(record)}}
    rows = []
    for record in sorted(jobs.values(), key=lambda r: r["started"], reverse=True)[:10]:
        code = _poll(record["id"])
        rows.append({"job_id": record["id"], "command": record["command"][:80],
                     "running": code is None, "exit_code": code})
    return {"success": True, "error": None, "data": {"jobs": rows}}


def prune() -> None:
    """Keep disk use tiny for years: drop old finished jobs, trim huge live logs."""
    now = time.time()
    with _lock:
        jobs = _load()
        changed = False
        ordered = sorted(jobs.values(), key=lambda r: r["started"], reverse=True)
        for index, record in enumerate(ordered):
            running = record["id"] in _procs and _procs[record["id"]].poll() is None or (
                record.get("exit_code") is None and _alive(record))
            too_old = now - float(record.get("ended") or record["started"]) > LOG_KEEP_SECONDS
            if not running and (too_old or index >= MAX_JOBS_KEPT):
                for key in ("out", "err"):
                    try:
                        Path(record[key]).unlink(missing_ok=True)
                    except OSError:
                        pass
                jobs.pop(record["id"], None)
                _procs.pop(record["id"], None)
                changed = True
                continue
            for key in ("out", "err"):
                _trim(record[key])
        if changed:
            _save(jobs)


def _trim(path: str) -> None:
    """A server that logs for weeks: keep only the last 256 KB once past 20 MB."""
    try:
        if os.path.getsize(path) <= MAX_LOG_BYTES:
            return
        tail, _size = _read_tail(path, TRIMMED_KEEP_BYTES)
        with open(path, "r+b") as handle:  # the child appends (O_APPEND), so this is safe
            handle.truncate(0)
            handle.write(("[older output trimmed]\n" + tail).encode("utf-8", "ignore"))
    except OSError:
        pass


def kill_now(job_id: str) -> None:
    """Used when a waiting turn is cancelled: the job must not outlive it."""
    proc = _procs.get(job_id)
    if proc is not None and proc.poll() is None:
        _kill_tree(proc.pid)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    _mark_ended(job_id, -9)

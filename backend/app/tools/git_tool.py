"""Verified local Git status and confirmed public-HTTPS clone tools."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict

from pydantic import BaseModel, Field

from backend.app.tools.tool_base import BaseTool


class GitArgs(BaseModel):
    directory: str = Field(".", description="Approved local Git working tree.")


class GitStatusTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="git_status",
            name="Git Repository Watcher",
            description="Reads verified branch, uncommitted paths, and last commit from a local Git working tree.",
            category="developer",
            tags=["git", "status", "branch", "commit", "uncommitted", "modified"],
            permission_level=0,
            args_model=GitArgs,
            usage_examples=["git_status(directory='.')"],
        )

    @staticmethod
    async def _git(cwd: Path, *arguments: str) -> tuple[int, str, str]:
        process = await asyncio.create_subprocess_exec(
            "git",
            *arguments,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15.0)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise RuntimeError("Git command timed out.") from exc
        return (
            int(process.returncode),
            stdout.decode("utf-8", "replace").strip(),
            stderr.decode("utf-8", "replace").strip(),
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        from backend.app.security.path_guard import check_path

        directory = Path(str(kwargs.get("directory") or ".")).expanduser().resolve(strict=False)
        decision = check_path(str(directory))
        if not decision["safe"]:
            return {
                "success": False,
                "error": f"Git directory blocked ({decision['reason']}): {directory}",
                "data": {},
            }
        if not directory.is_dir():
            return {"success": False, "error": f"Git directory does not exist: {directory}", "data": {}}
        try:
            code, inside, error = await self._git(directory, "rev-parse", "--is-inside-work-tree")
            if code != 0 or inside.lower() != "true":
                return {
                    "success": False,
                    "error": f"Not a Git working tree: {directory} ({error or 'verification failed'})",
                    "data": {"status": "unavailable", "directory": str(directory)},
                }

            branch_code, branch, branch_error = await self._git(directory, "branch", "--show-current")
            if branch_code != 0:
                raise RuntimeError(branch_error or "Could not read Git branch.")
            if not branch:
                head_code, head, head_error = await self._git(directory, "rev-parse", "--short", "HEAD")
                if head_code != 0:
                    raise RuntimeError(head_error or "Could not read detached HEAD.")
                branch = f"DETACHED@{head}"

            status_code, status_text, status_error = await self._git(directory, "status", "--porcelain")
            if status_code != 0:
                raise RuntimeError(status_error or "Could not read Git status.")
            uncommitted_files = []
            for line in status_text.splitlines()[:50]:
                if len(line) >= 4:
                    uncommitted_files.append(line[3:])

            log_code, last_commit, log_error = await self._git(directory, "log", "-1", "--pretty=%s")
            if log_code != 0:
                # A valid repository can have no commits yet; report that state explicitly.
                if "does not have any commits" in log_error.lower() or "unknown revision" in log_error.lower():
                    last_commit = "No commits yet"
                else:
                    raise RuntimeError(log_error or "Could not read last commit.")
        except Exception as exc:
            return {
                "success": False,
                "error": f"Failed to read verified Git status: {exc}",
                "data": {"status": "unavailable", "directory": str(directory)},
            }

        return {
            "success": True,
            "data": {
                "directory": str(directory),
                "branch": branch,
                "uncommitted_files": uncommitted_files,
                "last_commit": last_commit,
            },
            "error": None,
        }


class GitCloneArgs(BaseModel):
    url: str = Field(..., description="Git repository URL to clone.")
    directory: str = Field(".", description="Target directory to clone into.")


class GitCloneTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="git_clone",
            name="Git Clone",
            description="Clones a public HTTPS Git repository into an approved local directory.",
            category="developer",
            tags=["git", "clone", "download", "repo"],
            permission_level=2,
            args_model=GitCloneArgs,
            usage_examples=["git_clone(url='https://github.com/org/repo.git', directory='repos')"],
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        url = kwargs.get("url", "").strip()
        directory = kwargs.get("directory", ".").strip()
        if not url:
            return {"success": False, "error": "url required", "data": {}}
        if any(char in (url + directory) for char in ";|&`$(){}<>"):
            return {"success": False, "error": "Unsafe characters blocked.", "data": {}}

        from backend.app.security.url_guard import validate_public_url
        if not url.lower().startswith("https://"):
            return {"success": False, "error": "Git clone URL must use public HTTPS.", "data": {}}
        url_ok, url_reason = validate_public_url(url)
        if not url_ok:
            return {"success": False, "error": f"Git clone URL blocked: {url_reason}", "data": {}}

        from backend.app.security.path_guard import check_path
        destination = Path(directory).expanduser().resolve(strict=False)
        decision = check_path(str(destination))
        if not decision["safe"]:
            return {"success": False, "error": f"Clone destination blocked ({decision['reason']}): {destination}", "data": {}}
        try:
            process = await asyncio.create_subprocess_exec(
                "git", "-c", "http.followRedirects=false", "clone", url, directory,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
            if process.returncode == 0:
                return {"success": True, "data": {"message": f"Cloned {url} into {directory}"}, "error": None}
            return {
                "success": False,
                "error": (stderr.decode("utf-8", "replace") or stdout.decode("utf-8", "replace") or "clone failed")[:200],
                "data": {},
            }
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return {"success": False, "error": "Clone timed out (120s) and was stopped.", "data": {}}
        except Exception as exc:
            return {"success": False, "error": f"Clone failed: {exc}", "data": {}}

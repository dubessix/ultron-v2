"""
Ultron GitHub Integration Tool
Manages GitHub repositories, stage/commit/push, branches, PRs, and issue queries
natively (Level 2 Security).

Phase 5 security hardening:
  - All git commands run ARG-BASED (create_subprocess_exec) — no shell string
    interpolation, so a commit message or arg can never inject shell commands.
  - The PAT is NEVER written into the remote URL or into any git config. It is
    supplied to `git push` only through a per-subprocess credential helper that
    reads the token from the subprocess environment, then the remote URL stays
    clean (https://github.com/<owner>/<repo>.git).
  - No hardcoded "dubessix" — the account owner is resolved from GITHUB_USERNAME_<n>.
  - When no real token is configured, it reports an honest "unavailable" state
    (never fake/dummy success data).
"""

import os
import httpx
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from backend.app.tools.tool_base import BaseTool

# Block dangerous shell metacharacters in free-text args as defense-in-depth
# (exec already prevents injection, but this stops surprises in URL/path building).
# Spaces are intentionally allowed (normal commit messages / titles contain them).
_UNSAFE = set(";|&`$(){}<>\"'\n\t")


class GitHubArgs(BaseModel):
    action: str = Field(..., description="Action to perform: commit_push, create_repo, create_pr, list_issues, search_code.")
    repo_name: Optional[str] = Field(None, description="GitHub repository name (e.g. 'Zora-uktron').")
    commit_message: Optional[str] = Field("feat: automated codebase commit", description="Message for staging commit.")
    pr_title: Optional[str] = Field(None, description="Title of the pull request.")
    pr_head: Optional[str] = Field("main", description="Source branch for PR.")
    pr_base: Optional[str] = Field("main", description="Target destination branch for PR.")
    search_query: Optional[str] = Field(None, description="Code or keyword search query.")
    account: Optional[int] = Field(1, description="GitHub account (1 or 2) to use for this action.")


class GitHubIntegrationTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="github_integration",
            name="GitHub Integration Workspace",
            description="Manages git commit and push pipelines, creates repositories, tracks PRs, and searches issues natively.",
            category="developer",
            tags=["github", "git", "commit", "push", "pr", "issue", "repository", "code"],
            permission_level=2,  # Level 2: Requires manual confirmation for push/commits
            args_model=GitHubArgs,
            usage_examples=[
                "github_integration(action='commit_push', commit_message='feat: optimize voice')"
            ]
        )
        self.workspace_root = Path(__file__).resolve().parent.parent.parent.parent

    # -- secure, arg-based git execution -----------------------------------
    async def _execute_git(self, args: List[str]) -> str:
        """Run a git command with an ARG LIST (no shell), returning stdout."""
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.workspace_root),
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode("utf-8", "ignore").strip())
        return stdout.decode("utf-8", "ignore").strip()

    async def _git_push_secure(self, token: str, owner: str) -> str:
        """
        Push to origin WITHOUT putting the token in the remote URL or git config.
        The PAT is injected only into the subprocess environment and handed to git
        through an inline credential helper, so it never lands in the URL, config,
        command line, or process listing.
        """
        helper = "!f() { test \"$1\" = get && echo username=$GIT_PUSH_USER && echo password=$GIT_PUSH_TOKEN; }; f"
        env = dict(os.environ)
        env["GIT_PUSH_USER"] = owner or "git"
        env["GIT_PUSH_TOKEN"] = token
        proc = await asyncio.create_subprocess_exec(
            "git", "-c", f"credential.helper={helper}", "push", "origin", "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.workspace_root),
            env=env,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode("utf-8", "ignore").strip())
        return stdout.decode("utf-8", "ignore").strip()

    @staticmethod
    def _unsafe_chars_present(*values: Optional[str]) -> bool:
        return any(
            v and any(ch in _UNSAFE for ch in v)
            for v in values
        )

    # -- entry point ---------------------------------------------------------
    async def execute(self, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action", "").lower()
        repo_name = kwargs.get("repo_name")
        commit_message = kwargs.get("commit_message", "feat: automated codebase commit")
        pr_title = kwargs.get("pr_title")
        pr_head = kwargs.get("pr_head", "main")
        pr_base = kwargs.get("pr_base", "main")
        search_query = kwargs.get("search_query")

        account = str(kwargs.get("account", 1))
        github_token = os.getenv(f"GITHUB_TOKEN_{account}") or os.getenv("GITHUB_TOKEN")
        account_owner = os.getenv(f"GITHUB_USERNAME_{account}") or os.getenv("GITHUB_USERNAME")

        # Honest availability: no real token -> GitHub is unavailable.
        if not github_token or "your_github" in github_token or "placeholder" in github_token.lower():
            return {
                "success": True,
                "data": {
                    "configured": False,
                    "account": account,
                    "owner": account_owner or "unknown",
                    "message": (
                        "GitHub integration is NOT configured — no GITHUB_TOKEN "
                        f"{'(' + str(account) + ')' if account else ''} found in .env. "
                        "Add GITHUB_TOKEN_<n> + GITHUB_USERNAME_<n> to enable GitHub actions."
                    ),
                },
                "error": None,
            }

        owner = account_owner or "unknown"

        if action == "commit_push":
            return await self._commit_and_push(github_token, owner, commit_message)

        if action == "create_repo":
            return await self._create_repo(github_token, repo_name)

        if action == "create_pr":
            return await self._create_pr(github_token, owner, repo_name, pr_title, pr_head, pr_base)

        if action == "list_issues":
            return await self._list_issues(github_token, owner, repo_name)

        if action == "search_code":
            return await self._search_code(github_token, owner, repo_name, search_query)

        return {"success": False, "error": f"Unsupported action '{action}'.", "data": {}}

    async def _commit_and_push(self, token: str, owner: str, commit_message: str) -> Dict[str, Any]:
        # Reject metacharacters in the commit message (defense-in-depth).
        if self._unsafe_chars_present(commit_message):
            return {"success": False, "error": "Commit message contains unsafe characters.", "data": {}}
        try:
            await self._execute_git(["add", "."])
            try:
                await self._execute_git(["commit", "-m", commit_message])
            except RuntimeError as e:
                if "nothing to commit" in str(e) or "clean" in str(e):
                    pass
                else:
                    raise
            push_output = await self._git_push_secure(token, owner)
            return {
                "success": True,
                "data": {
                    "message": "Repository successfully synchronized and pushed.",
                    "owner": owner,
                    "commit": commit_message,
                    "push_log": push_output,
                },
                "error": None,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to commit & push changes: {e}", "data": {}}

    async def _create_repo(self, token: str, repo_name: Optional[str]) -> Dict[str, Any]:
        if not repo_name or self._unsafe_chars_present(repo_name):
            return {"success": False, "error": "repo_name is required and must be safe.", "data": {}}
        url = "https://api.github.com/user/repos"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        payload = {"name": repo_name, "private": True}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(url, headers=headers, json=payload)
                if res.status_code == 201:
                    return {"success": True, "data": {"message": f"Created private repo '{repo_name}'.", "clone_url": res.json().get("clone_url")}, "error": None}
                return {"success": False, "error": f"GitHub API failed {res.status_code}: {res.text}", "data": {}}
        except Exception as e:
            return {"success": False, "error": f"API connection crash: {e}", "data": {}}

    async def _create_pr(self, token: str, owner: str, repo_name: Optional[str], pr_title: Optional[str], pr_head: str, pr_base: str) -> Dict[str, Any]:
        if not pr_title or not repo_name or self._unsafe_chars_present(pr_title, pr_head, pr_base):
            return {"success": False, "error": "pr_title and repo_name are required (and safe).", "data": {}}
        if owner == "unknown":
            return {"success": False, "error": "Cannot create PR: GitHub owner (GITHUB_USERNAME_<n>) not configured.", "data": {}}
        url = f"https://api.github.com/repos/{owner}/{repo_name}/pulls"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        payload = {"title": pr_title, "head": pr_head, "base": pr_base}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(url, headers=headers, json=payload)
                if res.status_code == 201:
                    return {"success": True, "data": {"message": f"PR opened: {pr_title}", "url": res.json().get("html_url")}, "error": None}
                return {"success": False, "error": f"GitHub PR creation failed: {res.text}", "data": {}}
        except Exception as e:
            return {"success": False, "error": f"API Connection crash: {e}", "data": {}}

    async def _list_issues(self, token: str, owner: str, repo_name: Optional[str]) -> Dict[str, Any]:
        if not repo_name or self._unsafe_chars_present(repo_name):
            return {"success": False, "error": "repo_name is required and safe.", "data": {}}
        if owner == "unknown":
            return {"success": False, "error": "Cannot query issues: GitHub owner not configured.", "data": {}}
        url = f"https://api.github.com/repos/{owner}/{repo_name}/issues"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.get(url, headers=headers)
                if res.status_code == 200:
                    issues = [{"title": i.get("title"), "number": i.get("number"), "state": i.get("state"), "url": i.get("html_url")} for i in res.json()[:5]]
                    return {"success": True, "data": {"issues": issues, "count": len(issues)}, "error": None}
                return {"success": False, "error": f"Failed to retrieve issues: {res.text}", "data": {}}
        except Exception as e:
            return {"success": False, "error": f"API Connection crash: {e}", "data": {}}

    async def _search_code(self, token: str, owner: str, repo_name: Optional[str], search_query: Optional[str]) -> Dict[str, Any]:
        if not search_query or self._unsafe_chars_present(search_query):
            return {"success": False, "error": "search_query is required and safe.", "data": {}}
        if owner == "unknown" or not repo_name:
            return {"success": False, "error": "search_code needs a configured owner + repo_name.", "data": {}}
        url = f"https://api.github.com/search/code?q={search_query}+repo:{owner}/{repo_name}"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.get(url, headers=headers)
                if res.status_code == 200:
                    items = [{"name": i.get("name"), "path": i.get("path"), "url": i.get("html_url")} for i in res.json().get("items", [])[:5]]
                    return {"success": True, "data": {"items": items, "count": len(items)}, "error": None}
                return {"success": False, "error": f"Failed to search code: {res.text}", "data": {}}
        except Exception as e:
            return {"success": False, "error": f"API Connection crash: {e}", "data": {}}

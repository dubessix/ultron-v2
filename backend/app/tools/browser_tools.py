"""
Ultron Production-Grade Browser Tools
Implements un-mocked WebBrowser controls: Open URL, Open Tab, Close Tab, Refresh, Back, Forward, and Close Browser.
Uses lightweight cross-platform shell key senders (xdotool on Linux, powershell on Windows)
to trigger active browser controls without heavy Selenium/Playwright dependencies, protecting 8GB RAM bounds.
"""

import re
import webbrowser
import httpx
import platform
import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Any
from pydantic import BaseModel, Field
from backend.app.tools.tool_base import BaseTool

# --- Validation Schemas ---

class OpenUrlArgs(BaseModel):
    url: str = Field(..., description="Target web URL address to open.")

class EmptyArgs(BaseModel):
    pass

class DownloadUrlArgs(BaseModel):
    url: str = Field(..., description="Target asset URL address to download.")
    save_path: str = Field(..., description="Target local destination file path.")

class ReadPageArgs(BaseModel):
    url: str = Field(..., description="Target web page URL address to read and parse.")

# --- Helper Key Senders ---

async def send_browser_shortcut(key_combo: str) -> bool:
    """Send a shortcut only when the required executable exits successfully."""
    try:
        if platform.system() == "Windows":
            powershell = shutil.which("powershell") or shutil.which("pwsh")
            if not powershell:
                return False
            script = (
                "$wshell = New-Object -ComObject wscript.shell; "
                f"$wshell.SendKeys('{key_combo}')"
            )
            proc = await asyncio.create_subprocess_exec(
                powershell, "-NoProfile", "-Command", script,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        else:
            xdotool = shutil.which("xdotool")
            if not xdotool:
                return False
            lowered = key_combo.lower()
            if "^w" in lowered or "ctrl+w" in lowered:
                key = "ctrl+w"
            elif "f5" in lowered:
                key = "F5"
            elif "%{left}" in lowered or "alt+left" in lowered:
                key = "alt+Left"
            elif "%{right}" in lowered or "alt+right" in lowered:
                key = "alt+Right"
            elif "%{f4}" in lowered or "alt+f4" in lowered:
                key = "alt+F4"
            else:
                return False
            proc = await asyncio.create_subprocess_exec(
                xdotool, "key", key,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        return await proc.wait() == 0
    except (OSError, ValueError):
        return False

# --- Tool Implementations ---

class OpenUrlTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="open_url",
            name="URL Opener",
            description="Opens a requested URL web page inside the default Chrome browser.",
            category="browser",
            tags=["browser", "url", "open", "chrome", "web"],
            permission_level=1, # Level 1: Automatically allowed (Requirement: Phase 5)
            args_model=OpenUrlArgs,
            usage_examples=["open_url(url='https://github.com')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        url = kwargs.get("url", "")
        from backend.app.security.url_guard import validate_browser_url
        ok, reason = validate_browser_url(url)
        if not ok:
            return {"success": False, "error": f"Browser URL blocked: {reason}", "data": {}}
        try:
            opened = bool(webbrowser.open(url))
            if not opened:
                return {"success": False, "error": "Default browser rejected the launch request.", "data": {}}
            return {"success": True, "data": {"message": f"Browser accepted URL: {url}", "url": url}, "error": None}
        except Exception as e:
            return {"success": False, "error": f"Failed to launch URL: {e}", "data": {}}

class OpenNewTabTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="open_new_tab",
            name="New Tab Opener",
            description="Opens a requested URL web page inside a new browser tab.",
            category="browser",
            tags=["browser", "tab", "new", "chrome"],
            permission_level=1, # Level 1: Automatically allowed (Requirement: Phase 5)
            args_model=OpenUrlArgs,
            usage_examples=["open_new_tab(url='https://stackoverflow.com')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        url = kwargs.get("url", "")
        from backend.app.security.url_guard import validate_browser_url
        ok, reason = validate_browser_url(url)
        if not ok:
            return {"success": False, "error": f"Browser URL blocked: {reason}", "data": {}}
        try:
            opened = bool(webbrowser.open_new_tab(url))
            if not opened:
                return {"success": False, "error": "Default browser rejected the new-tab request.", "data": {}}
            return {"success": True, "data": {"message": f"Browser accepted new tab: {url}", "url": url}, "error": None}
        except Exception as e:
            return {"success": False, "error": f"Failed to open tab: {e}", "data": {}}

class CloseCurrentTabTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="close_tab",
            name="Tab Closer",
            description="Closes the currently active browser tab using system keyboard controls. Never closes browser window.",
            category="browser",
            tags=["browser", "tab", "close", "remove"],
            permission_level=2, # Level 2: Requires manual confirmation
            args_model=EmptyArgs,
            usage_examples=["close_tab()"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        # Sends Ctrl+W macro shortcut natively to close active tab
        success = await send_browser_shortcut("^w" if platform.system() == "Windows" else "ctrl+w")
        if success:
            return {"success": True, "data": {"message": "Active browser tab closed successfully."}, "error": None}
        return {"success": False, "error": "Failed to close active tab. System command macro error.", "data": {}}

class RefreshPageTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="refresh_page",
            name="Page Refresher",
            description="Refreshes the active browser tab page natively.",
            category="browser",
            tags=["browser", "refresh", "reload"],
            permission_level=1, # Level 1
            args_model=EmptyArgs,
            usage_examples=["refresh_page()"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        success = await send_browser_shortcut("{F5}" if platform.system() == "Windows" else "f5")
        if success:
            return {"success": True, "data": {"message": "Browser page refreshed successfully."}, "error": None}
        return {"success": False, "error": "Failed to execute page refresh.", "data": {}}

class BackTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="browser_back",
            name="Browser Navigation Back",
            description="Navigates back to the previous page in the browser history.",
            category="browser",
            tags=["browser", "back", "previous"],
            permission_level=1, # Level 1
            args_model=EmptyArgs,
            usage_examples=["browser_back()"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        success = await send_browser_shortcut("%{LEFT}" if platform.system() == "Windows" else "alt+left")
        if success:
            return {"success": True, "data": {"message": "Navigated back successfully."}, "error": None}
        return {"success": False, "error": "Failed to navigate back.", "data": {}}

class ForwardTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="browser_forward",
            name="Browser Navigation Forward",
            description="Navigates forward to the next page in the browser history.",
            category="browser",
            tags=["browser", "forward", "next"],
            permission_level=1, # Level 1
            args_model=EmptyArgs,
            usage_examples=["browser_forward()"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        success = await send_browser_shortcut("%{RIGHT}" if platform.system() == "Windows" else "alt+right")
        if success:
            return {"success": True, "data": {"message": "Navigated forward successfully."}, "error": None}
        return {"success": False, "error": "Failed to navigate forward.", "data": {}}

class CloseBrowserTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="close_browser",
            name="Browser Window Closer",
            description="Closes the entire browser window recursively. Requires explicit confirmation.",
            category="browser",
            tags=["browser", "close", "quit", "window"],
            permission_level=3, # Level 3: Dangerous (Requires confirmation)
            args_model=EmptyArgs,
            usage_examples=["close_browser()"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        # Sends Alt+F4 macro to close browser window natively
        success = await send_browser_shortcut("%{F4}" if platform.system() == "Windows" else "alt+f4")
        if success:
            return {"success": True, "data": {"message": "Entire browser window closed successfully."}, "error": None}
        return {"success": False, "error": "Failed to close browser window.", "data": {}}

class DownloadFileTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="download_file",
            name="Asset Downloader",
            description="Downloads a remote file asset directly to the local directory path asynchronously.",
            category="browser",
            tags=["browser", "download", "fetch", "file"],
            permission_level=2,
            args_model=DownloadUrlArgs,
            usage_examples=["download_file(url='https://example.com/logo.png', save_path='data\\logo.png')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        url = kwargs.get("url", "")
        save_path = Path(kwargs.get("save_path", "")).resolve()

        from backend.app.security.path_guard import check_path
        from backend.app.security.url_guard import (
            MAX_DOWNLOAD_BYTES, MAX_REDIRECTS, response_peer_is_approved,
            validate_public_url_details, validate_redirect,
        )

        path_decision = check_path(str(save_path))
        if not path_decision["safe"]:
            return {"success": False, "error": f"Download destination blocked ({path_decision['reason']}): {save_path}", "data": {}}

        current_url = url
        save_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            async with httpx.AsyncClient(follow_redirects=False, timeout=20.0) as client:
                for redirect_count in range(MAX_REDIRECTS + 1):
                    details = validate_public_url_details(current_url)
                    if not details["safe"]:
                        return {"success": False, "error": f"URL blocked (SSRF guard): {details['reason']}", "data": {}}

                    async with client.stream("GET", current_url) as response:
                        peer_ok, peer_reason = response_peer_is_approved(response, details["addresses"])
                        if not peer_ok:
                            return {"success": False, "error": f"URL blocked (SSRF peer guard): {peer_reason}", "data": {}}
                        if response.status_code in {301, 302, 303, 307, 308}:
                            if redirect_count >= MAX_REDIRECTS:
                                return {"success": False, "error": "Too many redirects.", "data": {}}
                            redirected = validate_redirect(current_url, response.headers.get("location", ""))
                            if not redirected["safe"]:
                                return {"success": False, "error": f"Redirect blocked (SSRF guard): {redirected['reason']}", "data": {}}
                            current_url = redirected["url"]
                            continue
                        if response.status_code != 200:
                            return {"success": False, "error": f"Download returned HTTP {response.status_code}", "data": {}}

                        declared = response.headers.get("content-length")
                        if declared and declared.isdigit() and int(declared) > MAX_DOWNLOAD_BYTES:
                            return {"success": False, "error": "Download Content-Length exceeds size limit.", "data": {}}
                        total = 0
                        fd, temp_name = tempfile.mkstemp(
                            dir=str(save_path.parent), prefix=f".{save_path.name}.", suffix=".download"
                        )
                        temp_path = Path(temp_name)
                        with os.fdopen(fd, "wb") as handle:
                            async for chunk in response.aiter_bytes(65536):
                                total += len(chunk)
                                if total > MAX_DOWNLOAD_BYTES:
                                    raise ValueError("Download exceeds size limit")
                                handle.write(chunk)
                            handle.flush()
                            os.fsync(handle.fileno())
                        os.replace(temp_path, save_path)
                        temp_path = None
                        return {
                            "success": True,
                            "data": {
                                "message": f"Downloaded verified asset to {save_path}",
                                "bytes": total,
                                "source_url": current_url,
                            },
                            "error": None,
                        }
            return {"success": False, "error": "Download redirect loop ended unexpectedly.", "data": {}}
        except Exception as e:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            return {"success": False, "error": f"Failed to complete asset download: {e}", "data": {}}

class ReadPageTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="read_current_page",
            name="Web Page Reader",
            description="Reads and extracts unformatted, clean text contents from a target URL.",
            category="browser",
            tags=["browser", "read", "parse", "html", "scrape"],
            permission_level=0, # Level 0: Read-Only (Auto Allow)
            args_model=ReadPageArgs,
            usage_examples=["read_current_page(url='https://example.com')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        current_url = kwargs.get("url", "")
        from backend.app.security.url_guard import (
            MAX_PAGE_BYTES, MAX_REDIRECTS, response_peer_is_approved,
            validate_public_url_details, validate_redirect,
        )

        try:
            async with httpx.AsyncClient(follow_redirects=False, timeout=15.0) as client:
                for redirect_count in range(MAX_REDIRECTS + 1):
                    details = validate_public_url_details(current_url)
                    if not details["safe"]:
                        return {"success": False, "error": f"URL blocked (SSRF guard): {details['reason']}", "data": {}}
                    async with client.stream("GET", current_url) as response:
                        peer_ok, peer_reason = response_peer_is_approved(response, details["addresses"])
                        if not peer_ok:
                            return {"success": False, "error": f"URL blocked (SSRF peer guard): {peer_reason}", "data": {}}
                        if response.status_code in {301, 302, 303, 307, 308}:
                            if redirect_count >= MAX_REDIRECTS:
                                return {"success": False, "error": "Too many redirects.", "data": {}}
                            redirected = validate_redirect(current_url, response.headers.get("location", ""))
                            if not redirected["safe"]:
                                return {"success": False, "error": f"Redirect blocked (SSRF guard): {redirected['reason']}", "data": {}}
                            current_url = redirected["url"]
                            continue
                        if response.status_code != 200:
                            return {"success": False, "error": f"Web server returned HTTP {response.status_code}", "data": {}}
                        chunks = []
                        total = 0
                        async for chunk in response.aiter_bytes(65536):
                            total += len(chunk)
                            if total > MAX_PAGE_BYTES:
                                return {"success": False, "error": "Web page exceeds read size limit.", "data": {}}
                            chunks.append(chunk)
                        html_content = b"".join(chunks).decode(response.encoding or "utf-8", "ignore")
                        clean_text = re.sub(r'<(script|style).*?>.*?</\1>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
                        clean_text = re.sub(r'<[^>]*?>', '', clean_text)
                        clean_text = re.sub(r'\s+', ' ', clean_text).strip()
                        summary = clean_text[:2000] + "..." if len(clean_text) > 2000 else clean_text
                        return {"success": True, "data": {"content": summary, "source_url": current_url}, "error": None}
            return {"success": False, "error": "Web redirect loop ended unexpectedly.", "data": {}}
        except Exception as e:
            return {"success": False, "error": f"Failed to scrape web page: {e}", "data": {}}

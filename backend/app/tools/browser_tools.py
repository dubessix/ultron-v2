"""
Ultron browser tools: open URLs and pages, download, read pages.
Tab work (close, switch, reload, back, forward, mute, read the live tab) goes
through the small Ultron Chrome extension (extension/chrome, V2 Step C3), so it
hits the real tab on Wayland and X11 and never closes Ultron's own tab.
"""

import re
import webbrowser
import httpx
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Literal
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
    url: str = Field("", description="A web address to fetch; leave empty to read the tab the owner is looking at.")
    which: str = Field("current", description="Which open tab to read when url is empty (e.g. 'youtube').")

class TabArgs(BaseModel):
    which: str = Field("current", description="current (default), or words from the tab title/site like 'youtube', or 'all youtube'.")

class BrowserTabsArgs(BaseModel):
    action: Literal["list", "switch", "mute", "unmute", "sleep", "reopen", "dedupe", "history"] = Field(
        "list", description="list tabs; switch/mute/unmute one; sleep background tabs to free RAM; reopen the last "
        "closed tab; dedupe closes duplicate tabs; history finds pages visited (which = what it was about).")
    which: str = Field("current", description="Tab words like 'youtube' or 'github'; 'current' by default. "
                       "For history: the words to search.")

# --- Real tabs through the Ultron Chrome extension (never key presses) ---

async def _tab_action(action: str, **args) -> Dict[str, Any]:
    """Keys go to whatever window has focus (often Ultron's own tab) and do nothing on
    Wayland, so every tab action goes through the extension and is checked."""
    from backend.app.core import browser_bridge

    return await browser_bridge.call(action, args)

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
            description="Closes a real browser tab (the one in front, or by name like 'youtube') and checks it is gone. Never Ultron's own tab.",
            category="browser",
            tags=["browser", "tab", "close", "remove"],
            permission_level=1,
            args_model=TabArgs,
            usage_examples=["close_tab()", "close_tab(which='youtube')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        result = await _tab_action("close", which=kwargs.get("which") or "current")
        data = result.get("data") or {}
        if result["success"] and data.get("need_choice"):
            titles = "; ".join(m.get("title", "") for m in data.get("matches", [])[:5])
            return {"success": False, "error": f"{data.get('note')} Open: {titles}", "data": data}
        return result

class RefreshPageTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="refresh_page",
            name="Page Refresher",
            description="Reloads the browser tab in front (never Ultron's own).",
            category="browser",
            tags=["browser", "refresh", "reload"],
            permission_level=1,
            args_model=EmptyArgs,
            usage_examples=["refresh_page()"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        return await _tab_action("reload")

class BackTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="browser_back",
            name="Browser Navigation Back",
            description="Goes back one page in the browser tab in front.",
            category="browser",
            tags=["browser", "back", "previous"],
            permission_level=1,
            args_model=EmptyArgs,
            usage_examples=["browser_back()"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        return await _tab_action("back")

class ForwardTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="browser_forward",
            name="Browser Navigation Forward",
            description="Goes forward one page in the browser tab in front.",
            category="browser",
            tags=["browser", "forward", "next"],
            permission_level=1,
            args_model=EmptyArgs,
            usage_examples=["browser_forward()"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        return await _tab_action("forward")

class CloseBrowserTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="close_browser",
            name="Browser Tabs Closer",
            description="Closes every browser tab except Ultron's own. Asks first.",
            category="browser",
            tags=["browser", "close", "quit", "window"],
            permission_level=3,
            args_model=EmptyArgs,
            usage_examples=["close_browser()"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        return await _tab_action("close_all")

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
            description="Reads the text of the tab the owner is looking at (no url), or of a web address.",
            category="browser",
            tags=["browser", "read", "parse", "html", "scrape"],
            permission_level=0, # Level 0: Read-Only (Auto Allow)
            args_model=ReadPageArgs,
            usage_examples=["read_current_page()", "read_current_page(url='https://example.com')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        current_url = str(kwargs.get("url") or "").strip()
        if not current_url:
            result = await _tab_action("read", which=kwargs.get("which") or "current")
            if result["success"]:
                data = result["data"]
                text = str(data.get("text") or "")
                data["content"] = text[:3000] + ("..." if len(text) > 3000 else "")
                data.pop("text", None)
            return result
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


class BrowserTabsTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="browser_tabs",
            name="Browser Tabs",
            description="Browser tabs: list, switch to / mute / unmute one by name, sleep background tabs to free "
                        "RAM (Chrome slow), reopen the tab just closed, close duplicate tabs, or find a page in "
                        "Chrome history (then open it with open_new_tab).",
            category="browser",
            tags=["browser", "tabs", "tab", "switch", "mute", "sleep", "memory", "reopen", "duplicate", "history"],
            permission_level=0,
            args_model=BrowserTabsArgs,
            usage_examples=["browser_tabs()", "browser_tabs(action='switch', which='youtube')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action") or "list"
        if action == "list":
            return await _tab_action("list")
        return await _tab_action(action, which=kwargs.get("which") or "current")


# --- Hands inside the open page (final list step 4) ---

class BrowserPageArgs(BaseModel):
    action: Literal["look", "click", "type", "scroll"] = Field(
        "look", description="look lists the page's buttons, links and boxes with numbers; then click, type or scroll.")
    target: str = Field("", description="Number from look, or the item's words. Scroll: up, down, top, bottom.")
    text: str = Field("", description="Text to type.")
    submit: bool = Field(False, description="After typing, press Enter / send the form.")
    confirmed: bool = Field(False, description="True only for a send, post, buy or delete the owner must approve.")
    which: str = Field("current", description="Which tab: current, or words like 'amazon'.")


# The last page step that needed the owner's yes, so the question can name it.
_last_needs_yes: Dict[str, str] = {}


def pending_label(target: str) -> str:
    """Words of the button/box that needed a yes (for the spoken question)."""
    if _last_needs_yes.get("target") == str(target or ""):
        return _last_needs_yes.get("label", "")
    return ""


class BrowserPageTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="browser_page",
            name="Browser Page Hands",
            description="Acts inside the open web page like a person: look (numbered buttons, links, boxes), click "
                        "one, type into a box (submit=true presses Enter), scroll. Look first, act by number. "
                        "Sending, posting, buying or deleting needs the owner's yes: it answers needs_yes, then call "
                        "again with confirmed=true. Never types passwords.",
            category="browser",
            tags=["browser", "page", "click", "type", "fill", "form", "search box", "button", "scroll"],
            permission_level=0,
            args_model=BrowserPageArgs,
            usage_examples=["browser_page(action='look')", "browser_page(action='click', target='3')",
                            "browser_page(action='type', target='search', text='usb c cable', submit=True)"],
        )

    def permission_for_arguments(self, arguments: Dict[str, Any]) -> int:
        return 2 if arguments.get("confirmed") else 0

    async def execute(self, **kwargs) -> Dict[str, Any]:
        from backend.app.core import browser_bridge

        action = str(kwargs.get("action") or "look")
        if action == "type" and not str(kwargs.get("text") or ""):
            return {"success": False, "error": "Say what to type.", "data": {}}
        args = {key: kwargs.get(key) for key in ("target", "text", "submit", "confirmed", "which")}
        args["which"] = args["which"] or "current"
        result = await browser_bridge.call(action, args, timeout=12.0)
        error = str(result.get("error") or "")
        if not result.get("success") and "Unknown browser action" in error:
            result["error"] = ("The Ultron browser helper is an older version. Open chrome://extensions and press "
                               "reload on Ultron Browser Hands once.")
        data = result.get("data") or {}
        if result.get("success") and data.get("needs_yes"):
            _last_needs_yes.clear()
            _last_needs_yes.update({"target": str(kwargs.get("target") or ""), "label": str(data.get("label") or "")})
        return result

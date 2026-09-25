"""
Ultron Production-Grade Web Search Tools
Implements un-mocked browser searches: Google, GitHub, StackOverflow, Reddit, Images, News, and Videos.
Automatically allowed (Level 1 permissions) to ensure seamless, non-intrusive operations.
"""

import webbrowser
import urllib.parse
from typing import Dict, Any
from pydantic import BaseModel, Field
from backend.app.tools.tool_base import BaseTool

# --- Validation Schemas ---

class SearchArgs(BaseModel):
    query: str = Field(..., description="Target search query keywords.")

def _open_verified(url: str) -> None:
    if not webbrowser.open(url):
        raise RuntimeError("Default browser rejected the search launch request.")


# --- Tool Implementations ---

class WebSearchArgs(BaseModel):
    query: str = Field(..., description="Target search query keywords.")
    open_in_browser: bool = Field(
        False,
        description="Also open the top result in the browser. Only when the owner asks to see/open it.",
    )


class GoogleSearchTool(BaseTool):
    """Jarvis web search: returns real results to the brain so it can answer.

    The old version only launched a browser, leaving the model blind. Now the
    top results (title, url, snippet) come back as data; opening the browser is
    optional and a browser failure never fails the search.
    """

    MAX_RESULTS = 5

    def __init__(self) -> None:
        super().__init__(
            tool_id="google_search",
            name="Web Search",
            description=(
                "Searches the live web and returns the top results (title, url, snippet) "
                "so you can answer with current facts. Set open_in_browser only when the "
                "owner wants the page opened."
            ),
            category="search",
            tags=["search", "google", "web", "find", "lookup", "latest", "internet"],
            permission_level=1, # Level 1: Automatically allowed (Requirement: Phase 5)
            args_model=WebSearchArgs,
            usage_examples=[
                "google_search(query='latest AI news')",
                "google_search(query='Vite React 19 config', open_in_browser=True)",
            ],
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        query = str(kwargs.get("query", "") or "").strip()
        open_in_browser = bool(kwargs.get("open_in_browser", False))
        escaped = urllib.parse.quote_plus(query)
        search_page = f"https://www.google.com/search?q={escaped}"

        results: list = []
        search_error = None
        try:
            from backend.app.tools._realsearch import real_web_search
            results = await real_web_search(query, limit=self.MAX_RESULTS) or []
        except Exception as exc:  # network/provider failure is reported, not hidden
            search_error = str(exc)

        top_url = results[0]["url"] if results else search_page
        browser_note = None
        # With no results the only useful fallback is showing the search page.
        if open_in_browser or not results:
            try:
                _open_verified(top_url)
                browser_note = "Opened in your browser."
            except Exception as exc:
                browser_note = f"Browser could not be opened: {exc}"

        if results:
            data = {
                "query": query,
                "url": top_url,
                "title": results[0].get("title", ""),
                "snippet": results[0].get("snippet", ""),
                "results": [
                    {
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "snippet": item.get("snippet", ""),
                    }
                    for item in results[: self.MAX_RESULTS]
                ],
                "message": f"Found {len(results[: self.MAX_RESULTS])} live results.",
            }
            if browser_note:
                data["browser"] = browser_note
            return {"success": True, "data": data, "error": None}

        if browser_note == "Opened in your browser.":
            return {"success": True, "data": {
                "query": query,
                "url": search_page,
                "results": [],
                "message": "No results could be read directly; the Google search page was opened.",
            }, "error": None}
        return {
            "success": False,
            "data": {"query": query, "url": search_page, "results": []},
            "error": (
                "Live web search returned no readable results"
                + (f" ({search_error})" if search_error else "")
                + (f"; {browser_note}" if browser_note else "")
            ),
        }

class GitHubSearchTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="github_search",
            name="GitHub Code Search",
            description="Launches a repository and code search query directly on GitHub.",
            category="search",
            tags=["search", "github", "code", "repo", "git"],
            permission_level=1, # Level 1: Automatically allowed (Requirement: Phase 5)
            args_model=SearchArgs,
            usage_examples=["github_search(query='fastapi clean architecture')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        query = kwargs.get("query", "")
        escaped = urllib.parse.quote_plus(query)
        url = f"https://github.com/search?q={escaped}"
        try:
            _open_verified(url)
            return {"success": True, "data": {"url": url}, "error": None}
        except Exception as e:
            return {"success": False, "error": f"Failed to run GitHub search: {e}", "data": {}}

class StackOverflowSearchTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="stackoverflow_search",
            name="StackOverflow Q&A Search",
            description="Launches a technical Q&A search on StackOverflow to find coding solutions.",
            category="search",
            tags=["search", "stackoverflow", "debug", "error", "solution"],
            permission_level=1, # Level 1: Automatically allowed (Requirement: Phase 5)
            args_model=SearchArgs,
            usage_examples=["stackoverflow_search(query='asyncio task timeout exception')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        query = kwargs.get("query", "")
        escaped = urllib.parse.quote_plus(query)
        url = f"https://stackoverflow.com/search?q={escaped}"
        try:
            _open_verified(url)
            return {"success": True, "data": {"url": url}, "error": None}
        except Exception as e:
            return {"success": False, "error": f"Failed to run StackOverflow search: {e}", "data": {}}

class RedditSearchTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="reddit_search",
            name="Reddit Discussion Search",
            description="Launches a discussion or review thread search query on Reddit.",
            category="search",
            tags=["search", "reddit", "discussion", "thread", "opinion"],
            permission_level=1, # Level 1
            args_model=SearchArgs,
            usage_examples=["reddit_search(query='PostgreSQL vs MongoDB for startup')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        query = kwargs.get("query", "")
        escaped = urllib.parse.quote_plus(query)
        url = f"https://www.reddit.com/search/?q={escaped}"
        try:
            _open_verified(url)
            return {"success": True, "data": {"url": url}, "error": None}
        except Exception as e:
            return {"success": False, "error": f"Failed to run Reddit search: {e}", "data": {}}

class ImageSearchTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="image_search",
            name="Google Image Search",
            description="Launches a visual graphics and asset image search on Google Images.",
            category="search",
            tags=["search", "images", "assets", "icons", "graphics"],
            permission_level=1, # Level 1
            args_model=SearchArgs,
            usage_examples=["image_search(query='matte black radial background')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        query = kwargs.get("query", "")
        escaped = urllib.parse.quote_plus(query)
        url = f"https://www.google.com/search?tbm=isch&q={escaped}"
        try:
            _open_verified(url)
            return {"success": True, "data": {"url": url}, "error": None}
        except Exception as e:
            return {"success": False, "error": f"Failed to run Image search: {e}", "data": {}}

class NewsArgs(BaseModel):
    query: str = Field(
        "top news today",
        description="News topic, e.g. 'India', 'AI startups', 'cricket'. Omit for top headlines.",
    )
    open_in_browser: bool = Field(False, description="Also open Google News in the browser.")


class NewsSearchTool(BaseTool):
    """Returns real, current headlines to the brain (browser is optional)."""

    MAX_RESULTS = 5

    def __init__(self) -> None:
        super().__init__(
            tool_id="news_search",
            name="Live News",
            description=(
                "Fetches current news headlines (title, url, snippet) for a topic so you can "
                "read or summarise them. Omit query for today's top headlines."
            ),
            category="search",
            tags=["search", "news", "events", "latest", "world", "headlines"],
            permission_level=1, # Level 1
            args_model=NewsArgs,
            usage_examples=["news_search(query='generative AI startup funding')", "news_search()"],
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        query = str(kwargs.get("query") or "top news today").strip()
        escaped = urllib.parse.quote_plus(query)
        url = f"https://news.google.com/search?q={escaped}"
        search_query = query if "news" in query.lower() else f"{query} latest news"

        results: list = []
        search_error = None
        try:
            from backend.app.tools._realsearch import real_web_search
            results = await real_web_search(search_query, limit=self.MAX_RESULTS) or []
        except Exception as exc:
            search_error = str(exc)

        browser_note = None
        if kwargs.get("open_in_browser") or not results:
            try:
                _open_verified(url)
                browser_note = "Opened Google News in your browser."
            except Exception as exc:
                browser_note = f"Browser could not be opened: {exc}"

        headlines = [
            {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("snippet", "")}
            for r in results[: self.MAX_RESULTS]
            if r.get("title")
        ]
        if headlines:
            data = {"query": query, "url": url, "headlines": headlines,
                    "message": f"Found {len(headlines)} current headlines."}
            if browser_note:
                data["browser"] = browser_note
            return {"success": True, "data": data, "error": None}
        if browser_note and browser_note.startswith("Opened"):
            return {"success": True, "data": {"query": query, "url": url, "headlines": [],
                    "message": "Headlines could not be read directly; Google News was opened."}, "error": None}
        return {"success": False, "data": {"query": query, "url": url, "headlines": []},
                "error": "No current headlines could be fetched"
                + (f" ({search_error})" if search_error else "")
                + (f"; {browser_note}" if browser_note else "")}

class VideoSearchTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="video_search",
            name="YouTube Video Search",
            description="Launches an educational tutorial and video search on YouTube.",
            category="search",
            tags=["search", "videos", "youtube", "tutorials", "guides"],
            permission_level=1, # Level 1
            args_model=SearchArgs,
            usage_examples=["video_search(query='React 19 hooks deep dive')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        query = kwargs.get("query", "")
        escaped = urllib.parse.quote_plus(query)
        url = f"https://www.youtube.com/results?search_query={escaped}"
        try:
            _open_verified(url)
            return {"success": True, "data": {"url": url}, "error": None}
        except Exception as e:
            return {"success": False, "error": f"Failed to run Video search: {e}", "data": {}}

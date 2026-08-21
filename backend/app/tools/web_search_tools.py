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

class GoogleSearchTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="google_search",
            name="Google Search Engine",
            description="Launches a Google search query inside your default browser.",
            category="search",
            tags=["search", "google", "web", "find"],
            permission_level=1, # Level 1: Automatically allowed (Requirement: Phase 5)
            args_model=SearchArgs,
            usage_examples=["google_search(query='Vite React 19 config')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        query = kwargs.get("query", "")
        escaped = urllib.parse.quote_plus(query)
        # Try to fetch real results and open the top ANSWER page (not a search page).
        try:
            from backend.app.tools._realsearch import real_web_search
            results = await real_web_search(query, limit=1)
            if results:
                url = results[0]["url"]
                _open_verified(url)
                return {"success": True, "data": {
                    "url": url,
                    "title": results[0]["title"],
                    "snippet": results[0]["snippet"],
                    "message": "Opened the top search result in your browser."
                }, "error": None}
        except Exception:
            pass
        # Fallback: open the Google search page.
        url = f"https://www.google.com/search?q={escaped}"
        try:
            _open_verified(url)
            return {"success": True, "data": {"url": url, "message": "Google search page successfully launched."}, "error": None}
        except Exception as e:
            return {"success": False, "error": f"Failed to run Google search: {e}", "data": {}}

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

class NewsSearchTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="news_search",
            name="Google News Search",
            description="Launches a real-time world event news query on Google News.",
            category="search",
            tags=["search", "news", "events", "latest", "world"],
            permission_level=1, # Level 1
            args_model=SearchArgs,
            usage_examples=["news_search(query='generative AI startup funding')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        query = kwargs.get("query", "")
        escaped = urllib.parse.quote_plus(query)
        url = f"https://news.google.com/search?q={escaped}"
        try:
            _open_verified(url)
            return {"success": True, "data": {"url": url}, "error": None}
        except Exception as e:
            return {"success": False, "error": f"Failed to run News search: {e}", "data": {}}

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

"""
Ultron Real Deep Research Tool
Asynchronously connects to the Tavily Search API using the configured TAVILY_API_KEY to retrieve
multi-source web summaries, URLs, and research data.
"""

import os
import httpx
from typing import Dict, Any
from pydantic import BaseModel, Field
from backend.app.tools.tool_base import BaseTool

class ResearchArgs(BaseModel):
    query: str = Field(..., min_length=2, max_length=500, description="Target search query topic for deep multi-source research.")

class TavilyResearchTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="tavily_research",
            name="Deep AI Research",
            description="Executes semantic web searches across multi-source registries and returns structured summaries.",
            category="research",
            tags=["research", "search", "web", "tavily", "google", "summary"],
            permission_level=0, # Level 0: Read-Only (no confirmation)
            args_model=ResearchArgs,
            usage_examples=["tavily_research(query='latest AI agents frameworks')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        query_str = kwargs.get("query", "")
        api_key = os.getenv("TAVILY_API_KEY")
        
        # If no key is set or is placeholder, use real (free, keyless) web results
        # instead of a fake summary, and open the top answer page in the browser.
        if not api_key or "your_tavily_api_key" in api_key:
            try:
                import webbrowser
                from backend.app.tools._realsearch import real_web_search
                results = await real_web_search(query_str, limit=3)
                if results:
                    # Open the most relevant answer page in the browser (not a search URL).
                    top_url = results[0]["url"]
                    try:
                        browser_opened = bool(webbrowser.open(top_url))
                    except Exception:
                        browser_opened = False
                    sources = [
                        {"name": r["title"], "url": r["url"], "snippet": r["snippet"]}
                        for r in results
                    ]
                    summary = (results[0]["snippet"] or results[0]["title"]).strip()
                    return {
                        "success": True,
                        "data": {
                            "topic": query_str,
                            "summary": summary or f"Here are the top web results for '{query_str}'.",
                            "sources": sources,
                            "opened_in_browser": top_url if browser_opened else None,
                            "browser_opened": browser_opened
                        },
                        "error": None
                    }
            except Exception:
                pass
            return {
                "success": False,
                "data": {
                    "status": "unavailable",
                    "topic": query_str,
                    "sources": [],
                    "opened_in_browser": None,
                },
                "error": f"No live web results could be verified for '{query_str}'.",
            }

        url = "https://api.tavily.com/search"
        payload = {
            "api_key": api_key,
            "query": query_str,
            "search_depth": "advanced",
            "include_answer": True
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, timeout=20.0)
                if response.status_code == 200:
                    res_data = response.json() or {}
                    answer = str(res_data.get("answer") or "").strip()
                    sources = []
                    for item in res_data.get("results", [])[:3]:
                        result_url = str(item.get("url") or "").strip()
                        if not result_url.startswith(("http://", "https://")):
                            continue
                        sources.append({
                            "name": str(item.get("title") or result_url).strip(),
                            "url": result_url,
                            "snippet": str(item.get("content") or "").strip()[:500],
                        })
                    if not sources:
                        return {
                            "success": False,
                            "data": {"status": "unavailable", "topic": query_str, "sources": []},
                            "error": "Tavily returned no verifiable source URLs.",
                        }
                    summary = answer or sources[0]["snippet"] or sources[0]["name"]
                    browser_opened = False
                    top_result_url = sources[0]["url"]
                    try:
                        import webbrowser
                        browser_opened = bool(webbrowser.open(top_result_url))
                    except Exception:
                        browser_opened = False
                    return {
                        "success": True,
                        "data": {
                            "topic": query_str,
                            "summary": summary,
                            "sources": sources,
                            "opened_in_browser": top_result_url if browser_opened else None,
                            "browser_opened": browser_opened,
                        },
                        "error": None,
                    }
                else:
                    return {"success": False, "error": f"Tavily API returned status: {response.status_code}", "data": {}}
            except Exception as e:
                return {"success": False, "error": f"Failed to complete Tavily search query: {e}", "data": {}}

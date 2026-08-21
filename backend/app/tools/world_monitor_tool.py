"""Verified public world/market feeds with standardized ToolResult payloads."""

from __future__ import annotations

import datetime
import re
from typing import Any, Dict, Optional

import httpx
from pydantic import BaseModel, Field

from backend.app.tools.tool_base import BaseTool


class WorldMonitorArgs(BaseModel):
    endpoint: str = Field(..., description="get_country_risk, list_earthquakes, get_fear_greed_index, list_market_quotes, get_internet_outages, list_military_flights, get_oil_opec_prices, or list_protests")
    parameters: Optional[Dict[str, Any]] = Field(default_factory=dict)


class WorldMonitorTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="world_monitor",
            name="World Monitor Intelligence Engine",
            description="Queries sourced public seismic, market, sentiment, and web-search feeds.",
            category="research",
            tags=["world", "monitor", "earthquake", "risk", "market", "outage", "geopolitics"],
            permission_level=1,
            args_model=WorldMonitorArgs,
            usage_examples=[
                "world_monitor(endpoint='list_earthquakes', parameters={'min_magnitude': 6.0})",
                "world_monitor(endpoint='list_market_quotes')",
            ],
        )

    async def _fetch_usgs_earthquakes(self, min_mag: float) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                response = await client.get(
                    "https://earthquake.usgs.gov/fdsnws/event/1/query",
                    params={"format": "geojson", "minmagnitude": min_mag, "limit": 5},
                )
        except Exception as exc:
            return {"success": False, "data": {"status": "unavailable", "earthquakes": []}, "error": f"USGS connection failure: {exc}"}
        if response.status_code != 200:
            return {"success": False, "data": {"status": "unavailable", "earthquakes": []}, "error": f"USGS returned HTTP {response.status_code}"}
        earthquakes = []
        for feature in (response.json() or {}).get("features", []):
            props = feature.get("properties") or {}
            magnitude = props.get("mag")
            timestamp_ms = props.get("time")
            if not isinstance(magnitude, (int, float)) or not isinstance(timestamp_ms, (int, float)):
                continue
            coordinates = ((feature.get("geometry") or {}).get("coordinates") or [])
            earthquakes.append({
                "title": props.get("title") or "Title not reported",
                "magnitude": float(magnitude),
                "place": props.get("place") or "Place not reported",
                "time": datetime.datetime.fromtimestamp(timestamp_ms / 1000, datetime.timezone.utc).isoformat(),
                "depth_km": coordinates[2] if len(coordinates) > 2 else None,
                "url": props.get("url"),
            })
        return {
            "success": True,
            "data": {
                "status": "live",
                "source": "USGS",
                "headline": f"USGS returned {len(earthquakes)} event(s) at or above magnitude {min_mag}.",
                "earthquakes": earthquakes,
            },
            "error": None,
        }

    async def _fetch_fear_greed_index(self) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get("https://api.alternative.me/fng/")
        except Exception as exc:
            return {"success": False, "data": {"status": "unavailable"}, "error": f"Fear & Greed connection failure: {exc}"}
        if response.status_code != 200:
            return {"success": False, "data": {"status": "unavailable"}, "error": f"Fear & Greed returned HTTP {response.status_code}"}
        rows = (response.json() or {}).get("data") or []
        if not rows:
            return {"success": False, "data": {"status": "unavailable"}, "error": "Fear & Greed returned no records."}
        row = rows[0]
        try:
            score = int(row["value"])
        except (KeyError, TypeError, ValueError):
            return {"success": False, "data": {"status": "unavailable"}, "error": "Fear & Greed score missing or invalid."}
        timestamp = None
        try:
            timestamp = datetime.datetime.fromtimestamp(int(row["timestamp"]), datetime.timezone.utc).isoformat()
        except (KeyError, TypeError, ValueError, OSError):
            pass
        classification = row.get("value_classification") or "Not reported"
        return {
            "success": True,
            "data": {
                "status": "live",
                "source": "Alternative.me",
                "headline": f"Current Fear & Greed score: {score} ({classification}).",
                "score": score,
                "classification": classification,
                "last_updated": timestamp,
            },
            "error": None,
        }

    async def _fetch_market_quotes(self) -> Dict[str, Any]:
        ids = "bitcoin,ethereum,binancecoin,solana"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://api.coingecko.com/api/v3/simple/price",
                    params={"ids": ids, "vs_currencies": "usd", "include_24hr_change": "true"},
                )
        except Exception as exc:
            return {"success": False, "data": {"status": "unavailable", "quotes": []}, "error": f"CoinGecko connection failure: {exc}"}
        if response.status_code != 200:
            return {"success": False, "data": {"status": "unavailable", "quotes": []}, "error": f"CoinGecko returned HTTP {response.status_code}"}
        symbols = {"bitcoin": "BTC", "ethereum": "ETH", "binancecoin": "BNB", "solana": "SOL"}
        quotes = []
        for asset, values in (response.json() or {}).items():
            price = values.get("usd") if isinstance(values, dict) else None
            change = values.get("usd_24h_change") if isinstance(values, dict) else None
            if not isinstance(price, (int, float)):
                continue
            quotes.append({
                "asset": asset,
                "symbol": symbols.get(asset, asset.upper()),
                "price_usd": float(price),
                "change_24h": float(change) if isinstance(change, (int, float)) else None,
            })
        if not quotes:
            return {"success": False, "data": {"status": "unavailable", "quotes": []}, "error": "CoinGecko returned no valid quotes."}
        return {
            "success": True,
            "data": {"status": "live", "source": "CoinGecko", "quotes": quotes},
            "error": None,
        }

    async def _search_live_news(self, query: str) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                response = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                    headers={"User-Agent": "Mozilla/5.0 (Ultron personal assistant)"},
                )
            if response.status_code == 200:
                snippets = re.findall(r'<a class="result__snippet[^>]*>(.*?)</a>', response.text, re.IGNORECASE)
                details = [re.sub(r"<[^>]*>", "", item).strip() for item in snippets[:3]]
                details = [item for item in details if item]
                if details:
                    return {
                        "success": True,
                        "data": {
                            "status": "live",
                            "source": "DuckDuckGo public search",
                            "headline": f"Public search returned {len(details)} result snippet(s) for '{query}'.",
                            "details": details,
                        },
                        "error": None,
                    }
        except Exception as exc:
            return {"success": False, "data": {"status": "unavailable", "details": []}, "error": f"Public search unavailable: {exc}"}
        return {"success": False, "data": {"status": "unavailable", "details": []}, "error": f"No verifiable public results for '{query}'."}

    async def execute(self, **kwargs) -> Dict[str, Any]:
        endpoint = str(kwargs.get("endpoint") or "").lower()
        parameters = kwargs.get("parameters") or {}
        if endpoint == "list_earthquakes":
            try:
                magnitude = float(parameters.get("min_magnitude", 5.0))
            except (TypeError, ValueError):
                return {"success": False, "data": {}, "error": "min_magnitude must be numeric."}
            return await self._fetch_usgs_earthquakes(magnitude)
        if endpoint == "get_fear_greed_index":
            return await self._fetch_fear_greed_index()
        if endpoint == "list_market_quotes":
            return await self._fetch_market_quotes()
        if endpoint == "get_country_risk":
            return await self._search_live_news(f"geopolitical country risk safety score {parameters.get('country', 'Iran')}")
        if endpoint == "get_internet_outages":
            return await self._search_live_news(f"internet outage network breakdown {parameters.get('country', 'Pakistan')}")
        if endpoint == "list_military_flights":
            return await self._search_live_news(f"military flights airspace movements {parameters.get('zone', 'Ukraine')}")
        if endpoint == "get_oil_opec_prices":
            return await self._search_live_news("oil prices crude OPEC production today")
        if endpoint == "list_protests":
            return await self._search_live_news(f"protests demonstrations {parameters.get('country', 'France')} today")
        return {"success": False, "data": {}, "error": f"Unsupported World Monitor endpoint '{endpoint}'."}

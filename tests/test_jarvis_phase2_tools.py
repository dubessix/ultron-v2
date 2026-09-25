"""Jarvis Phase 2 contract: tools give the brain real data, not just a browser tab."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from backend.app.tools.weather_tool import WeatherTool
from backend.app.tools.web_search_tools import GoogleSearchTool, NewsSearchTool

FORECAST = {
    "current_weather": {"temperature": 25.6, "weathercode": 61, "windspeed": 9.0, "time": "2026-09-24T10:00"},
    "hourly": {"time": ["2026-09-24T10:00"], "temperature_2m": [25.6], "weathercode": [61]},
    "daily": {"time": ["2026-09-24"], "temperature_2m_max": [29.0], "weathercode": [61]},
}
GEO = {"results": [{"name": "Bhātpāra", "admin1": "West Bengal", "country": "India",
                    "latitude": 22.87, "longitude": 88.41}]}
RESULTS = [
    {"title": f"Result {i}", "url": f"https://example.com/{i}", "snippet": f"snippet {i}"}
    for i in range(7)
]


def _resp(body):
    response = Mock(status_code=200)
    response.json.return_value = body
    return response


class TestWeatherByCity(unittest.TestCase):
    def test_city_is_geocoded_and_labelled(self):
        async def fake_get(url, params=None, **_):
            return _resp(GEO if "geocoding" in url else FORECAST)

        with patch("backend.app.tools.weather_tool.httpx.AsyncClient.get", new=AsyncMock(side_effect=fake_get)):
            result = asyncio.run(WeatherTool().execute(city="Bhatpara"))
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["location"], "Bhātpāra, West Bengal, India")
        self.assertEqual(result["data"]["temp"], "25.6°C")
        self.assertEqual(result["data"]["coordinates"]["latitude"], 22.87)

    def test_unknown_city_fails_honestly(self):
        with patch("backend.app.tools.weather_tool.httpx.AsyncClient.get",
                   new=AsyncMock(return_value=_resp({"results": []}))):
            result = asyncio.run(WeatherTool().execute(city="Xqzzyplace"))
        self.assertFalse(result["success"])
        self.assertIn("Xqzzyplace", result["error"])

    def test_coordinates_still_work(self):
        with patch("backend.app.tools.weather_tool.httpx.AsyncClient.get",
                   new=AsyncMock(return_value=_resp(FORECAST))):
            result = asyncio.run(WeatherTool().execute(latitude=22.57, longitude=88.36))
        self.assertTrue(result["success"])


class TestSearchReturnsResultsToBrain(unittest.TestCase):
    def test_google_search_returns_top_five_without_opening_browser(self):
        with patch("backend.app.tools._realsearch.real_web_search", new=AsyncMock(return_value=RESULTS)), \
                patch("webbrowser.open", return_value=True) as browser:
            result = asyncio.run(GoogleSearchTool().execute(query="latest AI news"))
        self.assertTrue(result["success"])
        self.assertEqual(len(result["data"]["results"]), 5)
        self.assertEqual(result["data"]["url"], "https://example.com/0")
        browser.assert_not_called()

    def test_browser_failure_does_not_fail_a_successful_search(self):
        with patch("backend.app.tools._realsearch.real_web_search", new=AsyncMock(return_value=RESULTS)), \
                patch("webbrowser.open", return_value=False):
            result = asyncio.run(GoogleSearchTool().execute(query="x", open_in_browser=True))
        self.assertTrue(result["success"])
        self.assertIn("could not be opened", result["data"]["browser"])

    def test_no_results_and_no_browser_is_honest_failure(self):
        with patch("backend.app.tools._realsearch.real_web_search", new=AsyncMock(return_value=[])), \
                patch("webbrowser.open", return_value=False):
            result = asyncio.run(GoogleSearchTool().execute(query="x"))
        self.assertFalse(result["success"])

    def test_news_returns_headlines_with_default_query(self):
        with patch("backend.app.tools._realsearch.real_web_search", new=AsyncMock(return_value=RESULTS)):
            result = asyncio.run(NewsSearchTool().execute())
        self.assertTrue(result["success"])
        self.assertEqual(len(result["data"]["headlines"]), 5)


if __name__ == "__main__":
    unittest.main()


class TestPersonalPathsStayGuarded(unittest.TestCase):
    def setUp(self):
        from backend.app.security.path_guard import resolve_project_root
        self.root = resolve_project_root("personal")["path"]

    def test_coding_turns_remain_confined_to_project(self):
        from backend.app.security.path_guard import resolve_agent_tool_arguments
        result = resolve_agent_tool_arguments(
            "delete_folder", {"folderpath": "/etc"}, self.root, confine_to_project=True)
        self.assertFalse(result["safe"])

    def test_personal_turns_still_block_system_and_unlisted_paths(self):
        from backend.app.security.path_guard import resolve_agent_tool_arguments
        for bad in ("/etc", "/var/log", "~/.ssh"):
            with self.subTest(path=bad):
                result = resolve_agent_tool_arguments(
                    "delete_folder", {"folderpath": bad}, self.root, confine_to_project=False)
                self.assertFalse(result["safe"])

    def test_desktop_word_maps_to_home_folder_before_guarding(self):
        from pathlib import Path
        from backend.app.security.path_guard import _personal_candidate
        self.assertEqual(_personal_candidate("Desktop/old", Path(self.root)), Path.home() / "Desktop" / "old")
        # Whole-disk Jarvis: a new plain name lands in the owner's home, not the app folder.
        self.assertEqual(_personal_candidate("notes", Path(self.root)), Path.home() / "notes")

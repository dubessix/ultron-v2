"""Regression tests for redirects, atomic downloads and honest external tools."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

_REAL_ASYNC_CLIENT = httpx.AsyncClient

from backend.app.runtime_paths import isolated_test_artifact_path
from backend.app.security.url_guard import validate_browser_url, validate_redirect
from backend.app.tools.browser_tools import DownloadFileTool, OpenUrlTool, ReadPageTool, send_browser_shortcut
from backend.app.tools.filesystem_search_tool import ConvertFileFormatTool
from backend.app.tools.git_tool import GitCloneTool
from backend.app.tools.music_tools import PlayMusicTool, SetVolumeTool
from backend.app.tools._realsearch import _is_organic_result_url
from backend.app.tools.spotify_tools import OpenSpotifyTool
from backend.app.tools.system_tools import CalculatorTool
from backend.app.tools.world_monitor_tool import WorldMonitorTool


class TestRedirectSafety(unittest.TestCase):
    def test_redirect_to_loopback_is_blocked(self):
        result = validate_redirect("https://example.com/start", "http://127.0.0.1/private")
        self.assertFalse(result["safe"])

    def test_browser_scheme_and_credentials_are_blocked(self):
        self.assertFalse(validate_browser_url("file:///etc/passwd")[0])
        self.assertFalse(validate_browser_url("https://user:pass@example.com")[0])
        self.assertTrue(validate_browser_url("http://127.0.0.1:5173")[0])


class TestSafeDownloadAndPageRead(unittest.IsolatedAsyncioTestCase):
    def _client_factory(self, handler):
        transport = httpx.MockTransport(handler)

        def factory(*_args, **_kwargs):
            return _REAL_ASYNC_CLIENT(transport=transport, follow_redirects=False, timeout=20.0)

        return factory

    async def test_download_blocks_redirect_to_private_target(self):
        target = isolated_test_artifact_path("phase4_download", "redirect.bin")

        def handler(_request):
            return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})

        with patch("backend.app.security.url_guard.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]), patch(
            "backend.app.tools.browser_tools.httpx.AsyncClient",
            self._client_factory(handler),
        ):
            result = await DownloadFileTool().execute(
                url="https://example.com/start", save_path=str(target)
            )
        self.assertFalse(result["success"])
        self.assertIn("Redirect blocked", result["error"])
        self.assertFalse(target.exists())

    async def test_oversized_download_preserves_existing_destination(self):
        target = isolated_test_artifact_path("phase4_download", "existing.bin")
        target.write_bytes(b"ORIGINAL")

        def handler(_request):
            return httpx.Response(200, content=b"x" * 2048)

        with patch("backend.app.security.url_guard.MAX_DOWNLOAD_BYTES", 1024), patch(
            "backend.app.security.url_guard.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]
        ), patch(
            "backend.app.tools.browser_tools.httpx.AsyncClient",
            self._client_factory(handler),
        ):
            result = await DownloadFileTool().execute(
                url="https://example.com/large", save_path=str(target)
            )
        self.assertFalse(result["success"])
        self.assertEqual(target.read_bytes(), b"ORIGINAL")
        self.assertEqual(list(target.parent.glob(f".{target.name}.*.download")), [])

    async def test_verified_download_replaces_atomically(self):
        target = isolated_test_artifact_path("phase4_download", "ok.bin")

        def handler(_request):
            return httpx.Response(200, content=b"verified")

        with patch("backend.app.security.url_guard.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]), patch(
            "backend.app.tools.browser_tools.httpx.AsyncClient",
            self._client_factory(handler),
        ):
            result = await DownloadFileTool().execute(
                url="https://example.com/file", save_path=str(target)
            )
        self.assertTrue(result["success"])
        self.assertEqual(target.read_bytes(), b"verified")

    async def test_page_reader_blocks_private_redirect(self):
        def handler(_request):
            return httpx.Response(302, headers={"location": "http://169.254.169.254/meta"})

        with patch("backend.app.security.url_guard.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]), patch(
            "backend.app.tools.browser_tools.httpx.AsyncClient",
            self._client_factory(handler),
        ):
            result = await ReadPageTool().execute(url="https://example.com/start")
        self.assertFalse(result["success"])
        self.assertIn("Redirect blocked", result["error"])


class TestHonestExternalOperations(unittest.IsolatedAsyncioTestCase):
    def test_search_result_filter_rejects_ad_tracking_urls(self):
        self.assertFalse(_is_organic_result_url(
            "https://duckduckgo.com/y.js?ad_domain=example.com&ad_provider=bingv7aa"
        ))
        self.assertFalse(_is_organic_result_url(
            "https://www.bing.com/aclick?ad_provider=bing&u=tracker"
        ))
        self.assertTrue(_is_organic_result_url("https://vite.dev/guide/"))

    async def test_browser_open_false_is_failure(self):
        with patch("backend.app.tools.browser_tools.webbrowser.open", return_value=False):
            result = await OpenUrlTool().execute(url="https://example.com")
        self.assertFalse(result["success"])

    async def test_missing_xdotool_is_failure(self):
        with patch("backend.app.tools.browser_tools.shutil.which", return_value=None):
            self.assertFalse(await send_browser_shortcut("ctrl+w"))

    async def test_missing_calculator_is_unavailable(self):
        with patch("backend.app.tools.system_tools.shutil.which", return_value=None):
            result = await CalculatorTool().execute()
        self.assertFalse(result["success"])
        self.assertIn("unavailable", result["error"])

    async def test_converter_outside_workspace_reports_success_without_post_write_error(self):
        source = isolated_test_artifact_path("phase4_convert", "input.json")
        destination = isolated_test_artifact_path("phase4_convert", "output.csv")
        source.write_text('[{"a": 1}]', encoding="utf-8")
        tool = ConvertFileFormatTool()
        # Keep its display workspace elsewhere to exercise the old relative_to failure.
        tool.workspace_root = Path(__file__).resolve().parent.parent
        result = await tool.execute(
            source_filepath=str(source), destination_filepath=str(destination)
        )
        self.assertTrue(result["success"])
        self.assertTrue(destination.exists())
        self.assertEqual(result["data"]["destination"], str(destination))

    async def test_git_clone_rejects_file_and_credential_urls(self):
        file_result = await GitCloneTool().execute(url="file:///tmp/repo", directory=str(isolated_test_artifact_path("phase4_clone")))
        credential_result = await GitCloneTool().execute(url="https://user:pass@example.com/repo.git", directory=str(isolated_test_artifact_path("phase4_clone2")))
        self.assertFalse(file_result["success"])
        self.assertFalse(credential_result["success"])

    async def test_music_without_player_and_mixer_is_honestly_unavailable(self):
        audio = isolated_test_artifact_path("phase4_music", "song.mp3")
        audio.write_bytes(b"not-real-audio")
        with patch("backend.app.tools.music_tools.shutil.which", return_value=None):
            play = await PlayMusicTool().execute(filepath=str(audio))
            volume = await SetVolumeTool().execute(level=50)
        self.assertFalse(play["success"])
        self.assertFalse(volume["success"])
        self.assertEqual(play["data"]["status"], "unavailable")
        self.assertEqual(volume["data"]["status"], "unavailable")

    async def test_spotify_web_launch_false_is_failure(self):
        with patch("backend.app.tools.spotify_tools.webbrowser.open", return_value=False):
            result = await OpenSpotifyTool().execute()
        self.assertFalse(result["success"])

    async def test_world_monitor_does_not_fabricate_fallback_intelligence(self):
        tool = WorldMonitorTool()
        with patch("backend.app.tools.world_monitor_tool.httpx.AsyncClient.get", side_effect=httpx.ConnectError("offline")):
            result = await tool._search_live_news("test region")
        self.assertFalse(result["success"])
        self.assertEqual(result["data"]["details"], [])
        self.assertEqual(result["data"]["status"], "unavailable")
        self.assertIn("unavailable", result["error"].lower())


if __name__ == "__main__":
    unittest.main()

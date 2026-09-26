"""V2 Step C3-C4: the browser bridge and the WebSocket origin guard."""

from __future__ import annotations

import asyncio
import json
import unittest

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.app.core import browser_bridge
from backend.app.websocket.connection_manager import EXTENSION_ID, origin_allowed

EXT = f"chrome-extension://{EXTENSION_ID}"


class TestOriginRules(unittest.TestCase):
    def test_other_websites_cannot_drive_ultron(self):
        self.assertFalse(origin_allowed("https://evil.example", "127.0.0.1:8000", "chat"))
        self.assertFalse(origin_allowed("http://evil.example:8000", "evil.example:8000", "chat"), "DNS rebinding")
        self.assertFalse(origin_allowed("chrome-extension://someotherextension", "127.0.0.1:8000", "browser"))
        self.assertFalse(origin_allowed(EXT, "127.0.0.1:8000", "chat"), "extension only on the browser channel")
        self.assertFalse(origin_allowed("http://127.0.0.1:5173", "127.0.0.1:8000", "browser"), "pages never on browser")

    def test_ultron_ui_programs_and_codespaces_are_allowed(self):
        self.assertTrue(origin_allowed("http://127.0.0.1:5173", "127.0.0.1:8000", "chat"))
        self.assertTrue(origin_allowed("http://localhost:8000", "localhost:8000", "events"))
        self.assertTrue(origin_allowed(None, "127.0.0.1:8000", "chat"), "scripts send no Origin")
        self.assertTrue(origin_allowed(EXT, "127.0.0.1:8000", "browser"))
        host = "abc-5173.app.github.dev"
        self.assertTrue(origin_allowed(f"https://{host}", host, "chat"))


class TestRealSockets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from backend.app.main import app
        cls.client = TestClient(app)

    def test_foreign_site_is_refused_on_events(self):
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect("/ws/events", headers={"origin": "https://evil.example"}) as ws:
                ws.receive_text()

    def test_extension_connects_and_gets_ultron_origins(self):
        with self.client.websocket_connect("/ws/browser", headers={"origin": EXT}) as ws:
            config = json.loads(ws.receive_text())
            self.assertEqual(config["type"], "config")
            self.assertIn("http://127.0.0.1:5173", config["ultron_origins"])

    def test_web_page_cannot_open_the_browser_channel(self):
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect("/ws/browser", headers={"origin": "http://127.0.0.1:5173"}) as ws:
                ws.receive_text()


class FakeExtension:
    """Answers like the real extension would."""

    def __init__(self, answer):
        self.answer, self.sent, self.closed = answer, [], False

    async def send_text(self, text):
        message = json.loads(text)
        self.sent.append(message)
        if "id" in message:
            reply = self.answer(message)
            if reply is not None:
                asyncio.get_running_loop().call_soon(browser_bridge.handle, json.dumps({"type": "reply", "id": message["id"], **reply}))

    async def close(self, code=1000):
        self.closed = True


class TestBridge(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        if browser_bridge._socket is not None:
            browser_bridge.detach(browser_bridge._socket)

    async def test_no_extension_gives_setup_steps(self):
        result = await browser_bridge.call("close", {"which": "current"})
        self.assertFalse(result["success"])
        self.assertIn("chrome://extensions", result["error"])
        self.assertIn("Load unpacked", result["error"])

    async def test_close_tab_tool_round_trip(self):
        from backend.app.tools.browser_tools import CloseCurrentTabTool
        ext = FakeExtension(lambda m: {"ok": True, "data": {"closed": 1, "verified_gone": True, "titles": ["YouTube"]}})
        await browser_bridge.attach(ext)
        result = await CloseCurrentTabTool().execute(which="youtube")
        self.assertTrue(result["success"], result)
        self.assertEqual(ext.sent[-1]["action"], "close")
        self.assertEqual(ext.sent[-1]["args"], {"which": "youtube"})

    async def test_many_matches_become_a_question_not_a_guess(self):
        from backend.app.tools.browser_tools import CloseCurrentTabTool
        data = {"closed": 0, "need_choice": True, "note": "2 tabs match. Say which one, or say \"all\".",
                "matches": [{"title": "YouTube - lofi"}, {"title": "YouTube - news"}]}
        await browser_bridge.attach(FakeExtension(lambda m: {"ok": True, "data": data}))
        result = await CloseCurrentTabTool().execute(which="youtube")
        self.assertFalse(result["success"])
        self.assertIn("lofi", result["error"])

    async def test_extension_error_is_reported(self):
        await browser_bridge.attach(FakeExtension(lambda m: {"ok": False, "error": "No open tab matches \"xyz\"."}))
        result = await browser_bridge.call("close", {"which": "xyz"})
        self.assertFalse(result["success"])
        self.assertIn("No open tab", result["error"])

    async def test_silent_extension_times_out_without_hanging(self):
        await browser_bridge.attach(FakeExtension(lambda m: None))
        result = await browser_bridge.call("list", timeout=0.2)
        self.assertFalse(result["success"])
        self.assertIn("did not answer", result["error"])
        self.assertEqual(browser_bridge._pending, {})

    async def test_disconnect_frees_waiting_calls(self):
        ext = FakeExtension(lambda m: None)
        await browser_bridge.attach(ext)
        task = asyncio.create_task(browser_bridge.call("list", timeout=5))
        await asyncio.sleep(0.05)
        browser_bridge.detach(ext)
        result = await asyncio.wait_for(task, 1)
        self.assertIn("disconnected", result["error"])

    async def test_newer_extension_replaces_older(self):
        old, new = FakeExtension(lambda m: None), FakeExtension(lambda m: {"ok": True, "data": {"count": 0}})
        await browser_bridge.attach(old)
        await browser_bridge.attach(new)
        self.assertTrue(old.closed)
        self.assertTrue((await browser_bridge.call("list"))["success"])

    async def test_read_live_tab_trims_text(self):
        from backend.app.tools.browser_tools import ReadPageTool
        await browser_bridge.attach(FakeExtension(lambda m: {"ok": True, "data": {"title": "T", "url": "u", "text": "x" * 5000}}))
        result = await ReadPageTool().execute()
        self.assertTrue(result["success"])
        self.assertLessEqual(len(result["data"]["content"]), 3003)
        self.assertNotIn("text", result["data"])

    def test_bad_messages_are_ignored(self):
        for junk in ("", "not json", "[]", '{"type":"reply","id":"x"}', '{"type":"reply","id":999}'):
            browser_bridge.handle(junk)


if __name__ == "__main__":
    unittest.main()

"""B9: tool results sent back to the brain carry the same facts in fewer tokens."""

from __future__ import annotations

import json
import unittest

from backend.app.core.orchestrator import CognitiveOrchestrator as O


class TestCompactResults(unittest.TestCase):
    def test_empty_fields_and_long_decimals_go(self):
        text = O._agent_result_content("system_metrics", {"success": True, "error": None, "data": {
            "cpu_percent": 23.456789, "ram_gb": 7.712345, "load": 0.000123456, "gpu": None, "extra": {}}})
        self.assertEqual(json.loads(text), {"tool": "system_metrics", "success": True, "data": {
            "cpu_percent": 23.46, "ram_gb": 7.71, "load": 0.000123}})

    def test_real_facts_stay_exact(self):
        body = "line 1\n  x = 0.123456789\n"
        data = {"content": body, "empty": "", "matches": [], "zero": 0, "no": False, "items": [None, 1.23456]}
        got = json.loads(O._agent_result_content("file_read", {"success": True, "data": data}))
        self.assertEqual(got["data"]["content"], body)
        self.assertEqual(got["data"]["empty"], "")
        self.assertEqual(got["data"]["matches"], [])
        self.assertEqual((got["data"]["zero"], got["data"]["no"]), (0, False))
        self.assertEqual(got["data"]["items"], [None, 1.23])  # list positions kept

    def test_failure_keeps_success_false_and_the_error(self):
        got = json.loads(O._agent_result_content("open_app", {"success": False, "data": {}, "error": "not installed"}))
        self.assertEqual(got, {"tool": "open_app", "success": False, "error": "not installed"})

    def test_smaller(self):
        raw = {"success": True, "error": None, "data": {"a": 1.23456789, "b": None, "c": {}, "d": 3.3333333333}}
        old = json.dumps({"tool": "t", **{"success": True, "data": raw["data"], "error": None}}, separators=(",", ":"))
        self.assertLess(len(O._agent_result_content("t", raw)), len(old))


if __name__ == "__main__":
    unittest.main()

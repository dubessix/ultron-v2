"""Fixes from the owner's first real day with V2 (chat log of 2026-09-27)."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.core import approval

ROOT = Path(__file__).resolve().parents[1]


class TestCloseAppAsksOnlyWhenWorkCanBeLost(unittest.TestCase):
    def test_players_and_viewers_close_without_a_question(self):
        for name in ("mpv", "MPV", "vlc", "vlc.desktop", "org.gnome.Totem", "Loupe", "spotify",
                     "gnome-system-monitor", "evince", "files"):
            self.assertFalse(approval.needs_ask("apps", {"action": "close", "name": name}, 2), name)

    def test_editors_and_unknown_apps_still_ask(self):
        for name in ("gedit", "code", "libreoffice", "firefox", "gimp", "", None):
            self.assertTrue(approval.needs_ask("apps", {"action": "close", "name": name}, 2), name)

    def test_high_risk_level_always_asks(self):
        self.assertTrue(approval.needs_ask("apps", {"action": "close", "name": "mpv"}, 3))


class TestOpenQuestionIsNamed(unittest.TestCase):
    """Owner: espeak question -> "why." -> Ultron explained the older mpv question."""

    def _orchestrator(self):
        from backend.app.core.orchestrator import CognitiveOrchestrator

        return CognitiveOrchestrator.__new__(CognitiveOrchestrator)

    def test_note_names_the_latest_question_and_waiting_step(self):
        orch = self._orchestrator()
        waiting = {"tool_id": "terminal_run", "summary": "command=sudo apt-get install -y espeak"}
        with patch.object(type(orch), "_last_ai_reply",
                          return_value="Should I run this command: sudo apt-get install -y espeak, Sir? Say yes or no."), \
             patch("backend.app.security.pending_actions.PendingActionRegistry.awaiting_for_session",
                   return_value=waiting):
            note = orch._open_question_note("s1")
        self.assertIn("[OPEN QUESTION]", note)
        self.assertIn("espeak", note)
        self.assertIn("terminal_run", note)
        self.assertIn("explain THIS step", note)
        self.assertIn("Never answer about an older question", note)

    def test_no_note_when_nothing_was_asked(self):
        orch = self._orchestrator()
        with patch.object(type(orch), "_last_ai_reply", return_value="Demon Slayer is playing, Sir."):
            self.assertEqual(orch._open_question_note("s1"), "")

    def test_note_never_breaks_a_turn(self):
        orch = self._orchestrator()
        with patch.object(type(orch), "_last_ai_reply", side_effect=RuntimeError("db gone")):
            self.assertEqual(orch._open_question_note("s1"), "")


class TestRulesFromTheChatLog(unittest.TestCase):
    def setUp(self):
        from backend.app.core.orchestrator import CognitiveOrchestrator

        self.rules = CognitiveOrchestrator._action_mandate_block()

    def test_research_uses_only_found_facts_lists_sources_and_saves_a_file(self):
        for phrase in ("Research or writing jobs", "google_search", "read_current_page",
                       "Write ONLY facts found in those results", "Sources list",
                       "file_write", "MS_Dhoni_Biography.md", "Never shorten"):
            self.assertIn(phrase, self.rules)

    def test_focus_timer_never_asks_for_title_or_time(self):
        self.assertIn("never ask for a title or start time", self.rules)

    def test_both_know_debjeet_built_them_and_save_what_he_shares(self):
        for name in ("ultron", "zora"):
            text = (ROOT / f"backend/app/personalities/{name}.md").read_text(encoding="utf-8")
            self.assertIn("Debjeet built you", text, name)
            self.assertIn("manage_memory remember", text, name)


if __name__ == "__main__":
    unittest.main()

"""Jarvis voice: the speaker never reads symbols, markdown, paths or JSON aloud."""

import unittest

from backend.app.utils.text_cleaner import clean_for_speech, speakable

SYMBOLS = set("*#_`|<>{}[]\\~^=@")


class TestSpeakable(unittest.TestCase):
    def assertClean(self, spoken):
        leaked = SYMBOLS & set(spoken)
        self.assertFalse(leaked, f"symbols leaked into speech: {leaked} in {spoken!r}")

    def test_markdown_emoji_units(self):
        out = speakable("**Done!** It's 25.6°C in Kolkata 🌧️ — wind 9.4 km/h, CPU 34%.")
        self.assertIn("25.6 degrees", out)
        self.assertIn("kilometres per hour", out)
        self.assertIn("34 percent", out)
        self.assertNotIn("🌧", out)
        self.assertClean(out)

    def test_paths_become_folder_names(self):
        self.assertIn("the Projects folder", speakable(r"Organized C:\Users\D\Documents\Projects now."))
        self.assertIn("the Downloads folder", speakable("Saved to /home/d/Downloads today."))
        self.assertIn("resume 2026 PDF", speakable("Found /home/d/Downloads/resume_2026.pdf"))

    def test_links_emails_domains(self):
        out = speakable("See [Python 3.14](https://www.python.org/x) or https://docs.python.org/3/ ; mail a.b@gmail.com")
        self.assertIn("Python 3.14", out)
        self.assertNotIn("https", out)
        self.assertIn("a dot b at gmail", out)
        self.assertClean(out)

    def test_code_json_tables_are_summarised(self):
        out = speakable("Fix:\n```python\ndef f():\n    return 1\n```\nResult: {\"success\": true, \"n\": 1}")
        self.assertIn("I've put the code on your screen.", out)
        self.assertNotIn("def f", out)
        self.assertNotIn("success", out)
        table = speakable("| Tool | Status |\n|---|---|\n| weather_tool | ok |")
        self.assertIn("weather tool, ok", table)
        self.assertClean(table)

    def test_symbols_become_words(self):
        out = speakable("Stress 0.81 > 0.75 & 6.5 GB / 16 GB → break for 10 min, issue #42, v2.3.1, ₹1,499")
        for words in ("is above", "and", "gigabytes of 16", "10 minutes", "number 42", "version 2.3.1", "1,499 rupees"):
            self.assertIn(words, out)
        self.assertClean(out)

    def test_lists_and_newlines_flow_as_sentences(self):
        out = speakable("Plan:\n1. Open VS Code\n2. Run npm install\n- Start server")
        self.assertEqual(out, "Plan. Open VS Code. Run npm install. Start server.")

    def test_voice_system_uses_speakable(self):
        self.assertEqual(clean_for_speech("a_b **x**"), speakable("a_b **x**"))

    def test_empty(self):
        self.assertEqual(speakable(""), "")


if __name__ == "__main__":
    unittest.main()

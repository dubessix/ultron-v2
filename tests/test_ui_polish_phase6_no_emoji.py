"""Phase 6 regressions: visible frontend controls use vector icons, not emoji."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend" / "src"
VISIBLE_SYMBOL = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]")


class TestNoVisibleEmoji(unittest.TestCase):
    def test_executable_frontend_has_no_emoji_or_text_glyph_controls(self):
        findings = []
        for path in sorted(FRONTEND.rglob("*")):
            if not path.is_file() or path.suffix not in {".js", ".jsx", ".css", ".html"}:
                continue
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if VISIBLE_SYMBOL.search(line) or "▸" in line:
                    findings.append(f"{path.relative_to(FRONTEND)}:{line_number}:{line.strip()}")
        self.assertEqual(findings, [], "Visible emoji/symbol controls remain:\n" + "\n".join(findings))

    def test_components_with_former_glyphs_use_lucide_icons(self):
        required = {
            "components/AppShell.jsx": ("Code2", "Check", "Mic"),
            "components/NotificationToast.jsx": ("X",),
            "components/RightPanel.jsx": ("CircleCheck", "Send", "ChevronRight"),
            "components/widgets/CalendarWidget.jsx": ("X",),
            "components/widgets/CodeOptimizerWidget.jsx": ("Zap",),
            "components/widgets/CodingWidget.jsx": ("Code2",),
            "components/widgets/FileExplorerWidget.jsx": ("Folder", "FileText"),
            "components/widgets/ReminderWidget.jsx": ("Clock3", "X"),
            "components/widgets/SecurityGuardianWidget.jsx": ("ShieldCheck",),
            "components/widgets/SemanticCodeGraphWidget.jsx": ("Workflow",),
            "components/widgets/TerminalWidget.jsx": ("Lightbulb",),
            "components/widgets/TodoWidget.jsx": ("Check", "X"),
        }
        for relative, icons in required.items():
            source = (FRONTEND / relative).read_text(encoding="utf-8")
            self.assertIn("lucide-react", source, relative)
            for icon in icons:
                self.assertIn(icon, source, f"{relative} missing {icon}")


if __name__ == "__main__":
    unittest.main()

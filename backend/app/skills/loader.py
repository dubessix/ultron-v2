"""Lazy, bounded selection of the existing coding skill markdown blocks."""

from __future__ import annotations

import re
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent
MAX_CODING_SKILL_CHARS = 4000
_CACHE: dict[str, str] = {}
_MULTI_FILE_HINT = re.compile(
    r"\b(multi[- ]file|several files|multiple files|whole feature|full feature|"
    r"authentication system|across the project|refactor the project)\b",
    re.IGNORECASE,
)


def load_skill(name: str) -> str:
    """Return one cached markdown skill block, or empty when unavailable."""
    if name in _CACHE:
        return _CACHE[name]
    path = SKILLS_DIR / f"{name}.md"
    if not path.exists():
        return ""
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError:
        content = ""
    _CACHE[name] = content
    return content


def load_coding_skills(
    user_prompt: str = "",
    max_chars: int = MAX_CODING_SKILL_CHARS,
) -> str:
    """Load core/project skills and add multi-file rules only when relevant."""
    names = ["coding_agent", "project_context"]
    if _MULTI_FILE_HINT.search(str(user_prompt or "")):
        names.insert(1, "multi_file_task")

    bounded_limit = min(MAX_CODING_SKILL_CHARS, max(500, int(max_chars)))
    blocks = []
    used = 0
    for name in names:
        content = load_skill(name)
        if not content:
            continue
        separator = 7 if blocks else 0
        if used + separator + len(content) > bounded_limit:
            continue
        blocks.append(content)
        used += separator + len(content)
    return "\n\n---\n\n".join(blocks)

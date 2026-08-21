"""
SkillLoader
Loads relevant skill instruction blocks from backend/app/skills/*.md so the
orchestrator can inject them into the system prompt only when needed — keeping
the base personality files clean and the prompt small.
"""
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent

# Cache loaded skill contents in memory (they are small and static).
_CACHE = {}


def load_skill(name: str) -> str:
    """Return the markdown contents of a skill file (cached). Empty if missing."""
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


def load_coding_skills() -> str:
    """Combine all coding-related skills into one block (dedup, clean)."""
    blocks = []
    for name in ("coding_agent", "multi_file_task", "project_context"):
        content = load_skill(name)
        if content:
            blocks.append(content)
    return "\n\n---\n\n".join(blocks)

"""
Ultron Text Cleaner
Cleans LLM output so it reads (and speaks) like a natural human — removing
awkward characters that models love but humans never use in speech: ellipses,
emojis, markdown, bullets, stray asterisks, and excess whitespace.

Applied to display AND voice paths, for both Ultron and Zora, so the spoken
response matches what the user reads — clean and human.
"""
import re

# Emoji ranges (broad but safe for our purpose)
_EMOJI_RE = re.compile(
    "[" 
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "\U0001F000-\U0001F0FF"
    "\U00002600-\U000026FF"
    "\U00002700-\U000027BF"
    "]+",
    flags=re.UNICODE,
)

_MARKDOWN_STRONG = re.compile(r"\*\*(.+?)\*\*")
_MARKDOWN_ITALIC = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_MARKDOWN_BULLET = re.compile(r"^\s*[-*•·]\s+", re.MULTILINE)
_MARKDOWN_HEADER = re.compile(r"^\s*#{1,6}\s+", re.MULTILINE)
_MARKDOWN_CODE = re.compile(r"`([^`]*)`")
_ELLIPSIS = re.compile(r"\.{2,}")
_DASHES = re.compile(r"[\u2013\u2014]")  # en/em dash
_DOUBLE_SPACE = re.compile(r"[ \t]{2,}")
_NEWLINES = re.compile(r"\n{3,}")
_ASTERISKS = re.compile(r"\*")


def clean_text(text: str) -> str:
    """Clean an AI response into human-natural text for display and speech."""
    if not text:
        return text

    t = text

    # 1. Markdown to plain text (before stripping * so content survives)
    t = _MARKDOWN_STRONG.sub(r"\1", t)   # **bold** -> bold
    t = _MARKDOWN_ITALIC.sub(r"\1", t)   # *italic* -> italic
    t = _MARKDOWN_CODE.sub(r"\1", t)     # `code` -> code
    t = _MARKDOWN_HEADER.sub("", t)      # # Heading -> Heading
    t = _MARKDOWN_BULLET.sub("", t)      # - item -> item

    # 2. Emojis
    t = _EMOJI_RE.sub("", t)

    # 3. Ellipses -> single period (so speech doesn't trail off)
    t = _ELLIPSIS.sub(".", t)

    # 4. En/em dashes -> hyphen (natural spoken pause)
    t = _DASHES.sub("-", t)

    # 5. Remaining asterisks — but keep *args / **kwargs (valid Python code tokens).
    # Protect them first, then strip remaining asterisks.
    t = t.replace("**kwargs", "KW").replace("*args", "AR")
    t = _ASTERISKS.sub("", t)
    t = t.replace("KW", "**kwargs").replace("AR", "*args")

    # 6. Whitespace tidy
    t = _DOUBLE_SPACE.sub(" ", t)
    t = _NEWLINES.sub("\n\n", t)

    # 7. Trim stray punctuation/space at boundaries
    t = t.strip()
    t = re.sub(r"\s+([.,!?])", r"\1", t)          # "word ," -> "word,"
    t = re.sub(r"([.,!?])([A-Za-z])", r"\1 \2", t)  # "done.Sir" -> "done. Sir"
    t = re.sub(r"([a-zA-Z0-9])\s*-\s*$", r"\1", t)  # trailing " -" -> remove

    return t.strip()


def clean_for_speech(text: str) -> str:
    """Speech-specific cleanup on top of clean_text (shorter, no markdown artifacts)."""
    t = clean_text(text)
    # Collapse newlines to spaces for smoother TTS (voice shouldn't read line breaks)
    t = re.sub(r"\s*\n+\s*", " ", t)
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip()

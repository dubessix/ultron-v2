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
    # "done.Sir" -> "done. Sir", but never split file names or links
    # ("notes.txt", "google.com", "v2.Final" stays readable enough).
    t = re.sub(r"(?<=[a-z0-9)\]])([.!?])([A-Z][a-z])", r"\1 \2", t)
    t = re.sub(r",(?=[A-Za-z])", ", ", t)
    t = re.sub(r"([a-zA-Z0-9])\s*-\s*$", r"\1", t)  # trailing " -" -> remove

    return t.strip()


# ---------------------------------------------------------------------------
# Jarvis speech layer: turn screen text into something a human butler SAYS.
# Nothing here is shown on screen — display keeps full detail (paths, links,
# code). Voice gets the meaning, never the symbols.
# ---------------------------------------------------------------------------

_CODE_FENCE = re.compile(r"```[\s\S]*?```")
_INLINE_JSON = re.compile(r"(?:\b[\w ]{1,24}:\s*)?\{[^\n]*?\"\s*:[^\n]*\}|\[[^\[\]\n]{40,}\]")
_FILENAME = re.compile(
    r"\b([\w\-]+)\.(pdf|docx?|xlsx?|pptx?|txt|md|csv|json|ya?ml|py|js|jsx|ts|tsx|html|css|"
    r"zip|rar|7z|png|jpe?g|gif|svg|mp3|wav|mp4|mkv|exe|msi|apk|log|ini|cfg|sql|db)\b",
    re.IGNORECASE,
)
_EXT_SPOKEN = {
    "pdf": "PDF", "doc": "Word file", "docx": "Word file", "xls": "Excel file",
    "xlsx": "Excel file", "ppt": "PowerPoint", "pptx": "PowerPoint", "txt": "text file",
    "md": "markdown file", "csv": "CSV file", "json": "jason file", "yml": "yaml file",
    "yaml": "yaml file", "py": "python file", "js": "JavaScript file", "jsx": "React file",
    "ts": "TypeScript file", "tsx": "React file", "html": "web page", "css": "style sheet",
    "zip": "zip file", "rar": "rar file", "7z": "7 zip file", "png": "image", "jpg": "photo",
    "jpeg": "photo", "gif": "gif", "svg": "image", "mp3": "MP3", "wav": "audio file",
    "mp4": "video", "mkv": "video", "exe": "installer", "msi": "installer", "apk": "app",
    "log": "log file", "ini": "settings file", "cfg": "settings file", "sql": "sequel file",
    "db": "database",
}
_MD_LINK = re.compile(r"\[([^\]]+)\]\((?:https?://|www\.)[^)]+\)")
_URL = re.compile(r"\b(?:https?://|www\.)([A-Za-z0-9.-]+)[^\s)\]>\"']*", re.IGNORECASE)
_EMAIL = re.compile(r"\b([A-Za-z0-9._%+-]+)@([A-Za-z0-9-]+)\.[A-Za-z.]{2,}\b")
_WIN_PATH = re.compile(r"\b[A-Za-z]:\\(?:[^\\\s,;:]+\\)*([^\\\s,;:]+)")
_POSIX_PATH = re.compile(r"(?<![\w/])(?:~|\.{1,2})?(?:/[\w\-]+(?:\.[\w\-]+)*){2,}/?")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}.*$", re.MULTILINE)
_TABLE_PIPE = re.compile(r"\s*\|\s*")
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+", re.MULTILINE)
_BLOCKQUOTE = re.compile(r"^\s*>+\s?", re.MULTILINE)
_SNAKE = re.compile(r"\b([a-z][a-z0-9]*)(?:_([a-z0-9]+))+\b")
_HASHTAG = re.compile(r"(?<!\w)#(\d+)")
_VERSION = re.compile(r"\bv(\d+(?:\.\d+)+)\b")
_TIME_AMPM = re.compile(r"\b(\d{1,2}):(\d{2})\s*([AaPp])\.?[Mm]\.?\b")
_TIME_24 = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")

_UNITS = [
    (re.compile(r"(-?\d+(?:\.\d+)?)\s*°\s*C\b"), r"\1 degrees"),
    (re.compile(r"(-?\d+(?:\.\d+)?)\s*°\s*F\b"), r"\1 degrees Fahrenheit"),
    (re.compile(r"(-?\d+(?:\.\d+)?)\s*°"), r"\1 degrees"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*%"), r"\1 percent"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*km/h\b", re.I), r"\1 kilometres per hour"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*GB\b"), r"\1 gigabytes"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*MB\b"), r"\1 megabytes"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*KB\b"), r"\1 kilobytes"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*TB\b"), r"\1 terabytes"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*GHz\b"), r"\1 gigahertz"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*ms\b"), r"\1 milliseconds"),
    (re.compile(r"\b1\s*(?:min|mins)\b"), "1 minute"),
    (re.compile(r"(\d+)\s*(?:min|mins)\b"), r"\1 minutes"),
    (re.compile(r"\b1\s*(?:hr|hrs)\b"), "1 hour"),
    (re.compile(r"(\d+)\s*(?:hr|hrs)\b"), r"\1 hours"),
    (re.compile(r"(\d+)\s*(?:sec|secs)\b"), r"\1 seconds"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*mm\b"), r"\1 millimetres"),
    (re.compile(r"₹\s*(\d[\d,]*(?:\.\d+)?)"), r"\1 rupees"),
    (re.compile(r"\$\s*(\d[\d,]*(?:\.\d+)?)"), r"\1 dollars"),
    (re.compile(r"€\s*(\d[\d,]*(?:\.\d+)?)"), r"\1 euros"),
    (re.compile(r"£\s*(\d[\d,]*(?:\.\d+)?)"), r"\1 pounds"),
]
_WORD_SYMBOLS = [
    ("->", ", "), ("=>", ", "), ("→", ", "), ("←", ", "), ("<-", ", "), (" / ", " of "),
    ("&&", " and "), ("||", " or "), (" & ", " and "), ("≈", " about "), ("~", " about "),
    ("≥", " at least "), ("≤", " at most "), (">=", " at least "), ("<=", " at most "),
    ("×", " times "), ("✓", ""), ("✔", ""), ("✅", ""), ("❌", ""), ("⚠", ""),
    (" > ", " is above "), (" < ", " is below "), (" · ", ", "), ("·", ", "), (" • ", ", "),
    ("+/-", " plus or minus "), ("±", " plus or minus "), ("…", "."),
]
# Everything a TTS engine would read aloud as a symbol name.
_LEFTOVER_SYMBOLS = re.compile(r"[<>{}\[\]|\\^`=_#*@~§¶•·►▶◆■□▪︎]+")
# Neural voices already read CPU, RAM, PDF, AI, 5:30 PM naturally; only fix the
# few words they mispronounce.
_SPOKEN_ACRONYMS = {"JSON": "jason", "SQL": "sequel", "GUI": "gooey", "YAML": "yamel"}
_DOMAIN = re.compile(r"\b([A-Za-z0-9-]+)\.(com|org|net|io|dev|ai|in|co|app|gov|edu)\b", re.IGNORECASE)


def _say_file(match: "re.Match[str]") -> str:
    stem = match.group(1).replace("_", " ").replace("-", " ").strip()
    return f"{stem} {_EXT_SPOKEN.get(match.group(2).lower(), match.group(2))}"


def _say_path(match: "re.Match[str]") -> str:
    tail = match.group(1) if match.lastindex else match.group(0)
    name = tail.rstrip("/\\").split("/")[-1].split("\\")[-1]
    return f"the {name} folder" if "." not in name else f"{name}"


def _say_posix_path(match: "re.Match[str]") -> str:
    parts = [p for p in match.group(0).split("/") if p and p not in ("~", ".", "..")]
    if not parts:
        return "your home folder"
    name = parts[-1].strip()
    return name if "." in name else f"the {name} folder"


def _say_time(match: "re.Match[str]") -> str:
    hour, minute, half = match.group(1), match.group(2), match.group(3).lower()
    suffix = "A M" if half == "a" else "P M"
    return f"{int(hour)} {suffix}" if minute == "00" else f"{int(hour)} {minute} {suffix}"


def _say_time24(match: "re.Match[str]") -> str:
    hour, minute = int(match.group(1)), match.group(2)
    return f"{hour} o'clock" if minute == "00" else f"{hour} {minute}"


def speakable(text: str) -> str:
    """Make any assistant reply safe to say out loud, Jarvis-style.

    - code blocks / JSON / tables -> short spoken summary ("I've put the code on screen.")
    - links -> the site name; emails -> "name at domain"
    - file paths -> "the Projects folder" / "report.pdf"
    - 25.6°C -> "25.6 degrees", 45% -> "45 percent", ₹500 -> "500 rupees", 5:30 PM -> "5 30 P M"
    - weather_tool -> "weather tool"; arrows/ampersands -> words
    - every other symbol (#, *, _, |, <, >, {, }, \\, `, =) is removed, never spelled
    """
    if not text:
        return ""
    t = str(text)

    had_code = bool(_CODE_FENCE.search(t))
    t = _CODE_FENCE.sub(" ", t)
    had_json = bool(_INLINE_JSON.search(t))
    t = _INLINE_JSON.sub(" ", t)

    had_table = bool(_TABLE_RULE.search(t))
    t = _TABLE_RULE.sub("", t)
    if had_table:
        t = "\n".join(
            ", ".join(c.strip() for c in line.strip().strip("|").split("|") if c.strip())
            if line.count("|") >= 2 else line
            for line in t.splitlines()
        )

    t = _MD_LINK.sub(r"\1", t)
    t = _URL.sub(lambda m: m.group(1).removeprefix("www.").split(".")[0].capitalize() + " link", t)
    t = _EMAIL.sub(lambda m: m.group(1).replace(".", " dot ") + " at " + m.group(2), t)
    t = _WIN_PATH.sub(_say_path, t)
    t = _POSIX_PATH.sub(_say_posix_path, t)

    t = _FILENAME.sub(_say_file, t)
    t = _DOMAIN.sub(lambda m: f"{m.group(1)} dot {m.group(2).lower()}", t)
    t = _BLOCKQUOTE.sub("", t)
    t = _NUMBERED.sub("", t)
    t = clean_text(t)
    t = re.sub(r"\s+-\s+", ", ", t)          # spoken dash pause -> comma

    for pattern, spoken in _UNITS:
        t = pattern.sub(spoken, t)
    t = _VERSION.sub(r"version \1", t)
    t = _HASHTAG.sub(r"number \1", t)
    t = _SNAKE.sub(lambda m: m.group(0).replace("_", " "), t)
    for symbol, spoken in _WORD_SYMBOLS:
        t = t.replace(symbol, spoken)
    for acronym, spoken in _SPOKEN_ACRONYMS.items():
        t = re.sub(rf"\b{acronym}\b", spoken, t)

    t = re.sub(r"(?<=\w)/(?=\w)", " or ", t)       # and/or -> and or
    t = re.sub(r"(?<=[a-z])\.(?=[a-z]{2,4}\b)", " dot ", t)  # sales.json -> sales dot json
    t = _LEFTOVER_SYMBOLS.sub(" ", t)
    t = re.sub(r"\(\s*\)", " ", t)
    t = re.sub(r"[()]", ", ", t)
    t = re.sub(r"\s*:\s*\n", ". ", t)
    t = re.sub(r"\s*\n+\s*", ". ", t)
    t = re.sub(
        r"\s*[,.;:!?](?:\s*[,.;:!?])+",
        lambda m: next((c for c in "?!." if c in m.group(0)), ","),
        t,
    )  # ", ." -> "."   ", ," -> ","
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    t = re.sub(r"([.!?])\s*\.", r"\1", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" ,;:")

    notes = []
    if had_code:
        notes.append("I've put the code on your screen.")
    if had_json and not had_code:
        notes.append("The full details are on screen.")
    if notes:
        t = (t + " " if t else "") + " ".join(notes)
    if t and t[-1] not in ".!?":
        t += "."
    return t.strip()


def clean_for_speech(text: str) -> str:
    """Speech path used by VoiceSystem.speak — the Jarvis speakable layer."""
    return speakable(text)

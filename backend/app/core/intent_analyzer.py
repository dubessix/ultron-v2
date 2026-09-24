"""
Ultron Core Intent Analyzer
Parses and classifies user queries into structured behavioral intents.
Runs entirely locally with 0MB RAM footprint.

Design rule (Phase 0.B): intents are *hints* for widgets, provider choice and
latency tracks — they never decide whether tools exist. Tool attachment is the
orchestrator's job; the LLM decides which declared tool to call. Therefore:
  - CODING no longer fires on the bare word "code" ("open VS Code" is not coding).
  - CONVERSATION only matches pure social turns (greeting/thanks small talk),
    so "thanks! now find my invoice pdf" stays an action turn.
  - Everyday Jarvis domains (weather, music, system, files, browser, search)
    get their own intents instead of falling through to EXPLANATION.
"""

import re


class IntentAnalyzer:
    def __init__(self) -> None:
        # Pure social turns: one or more social fragments and nothing else
        # ("Hi there, good morning!" / "thanks jarvis" / "how are you today?").
        fragment = (
            r"(?:(?:hi|hello|hey|yo|hiya|namaskar|namaste|salam|salaam|adab)"
            r"(?:\s+(?:there|ultron|jarvis|zora|bro|buddy|yaar))?"
            r"|good\s+(?:morning|afternoon|evening|night)"
            r"(?:\s+(?:ultron|jarvis|zora|bro|buddy))?"
            r"|(?:thanks|thank\s+you|thx|shukriya|dhanyabad)"
            r"(?:\s+(?:a\s+lot|so\s+much|ultron|jarvis|zora|bro|buddy|yaar))?"
            r"|welcome|okay|ok|alright|cool|nice|great|awesome|good|fine|sure|bye|goodbye|see\s+you"
            r"|(?:how\s+(?:are|r)\s+(?:you|u)|how'?s\s+it\s+going|what'?s\s+up|wassup|kaise\s+ho|kem\s+cho)"
            r"(?:\s+(?:today|doing|right\s+now|man|bro|ultron|jarvis|zora))?)"
        )
        self._conversation_fullmatch = re.compile(
            rf"^\s*{fragment}(?:[\s,!.?;]+{fragment})*\s*[!.?,;]*\s*$",
            re.IGNORECASE,
        )
        # Greeting followed by pure small talk (still conversational).
        self._conversation_smalltalk = re.compile(
            r"^\s*(?:hi|hello|hey|yo|namaskar|good\s+(?:morning|afternoon|evening|night))"
            r"[\s,]*(?:ultron|jarvis)?[\s,]*"
            r"(?:how\s+(?:are|r)\s+(?:you|u)|how'?s\s+it\s+going|what'?s\s+up|kaise\s+ho|kem\s+cho)"
            r"[\w\s'?,.!]*$",
            re.IGNORECASE,
        )

        # Predefined regex patterns for high-speed, local intent matching.
        # Checked in priority order below.
        self._patterns = {
            # Strong coding signal: an action verb bound to a code artifact.
            "CODING": re.compile(
                r"\b(make|write|build|create|fix|refactor|implement|generate|review|"
                r"update|edit|add|remove|delete) (a |the |an |this |my )?(code |source )?(api|endpoint|route|"
                r"function|class|module|file|script|schema|config|middleware|component|"
                r"css|html|jsx|auth|login|signup|oauth|database|model|handler)\b|"
                r"\b(coding|source code|write code|fix (?:the |my |some |this )?code|"
                r"refactor(?:ing)? (?:the |my |this )?code|debug this|review the code|"
                r"optimize the code|optimise the code|add feature|build feature|"
                r"auth api|make api|run pytest|unit test)\b",
                re.IGNORECASE,
            ),
            "WEATHER": re.compile(
                r"\b(weather|forecast|temperature|rain|raining|rains|umbrella|"
                r"humidity|heatwave|cold outside|barish)\b",
                re.IGNORECASE,
            ),
            "MUSIC": re.compile(
                r"\b(music|song|songs|track|tracks|spotify|volume|playlist|"
                r"gaana|audio|volume up|volume down|louder)\b",
                re.IGNORECASE,
            ),
            "SYSTEM": re.compile(
                r"\b(cpu|ram|battery|disk|storage|screenshot|uptime|metrics|"
                r"system (?:status|health|info|usage)|memory usage|processes?)\b",
                re.IGNORECASE,
            ),
            "PLANNING": re.compile(
                r"\b(plan|schedule|todo|task|calendar|sprint|reminder|remind|alarm)\b",
                re.IGNORECASE,
            ),
            "FILE_OPS": re.compile(
                r"\b(folders?|files?|downloads?|documents?|desktop|organize|organise|"
                r"zip|compress|extract|unzip|pdf|invoice|rename|backup folder)\b",
                re.IGNORECASE,
            ),
            "BROWSER": re.compile(
                r"\b(chrome|browser|website|webpage|web page|url|new tab|firefox)\b",
                re.IGNORECASE,
            ),
            "SEARCH": re.compile(
                r"\b(search|google|googling|lookup|look up|find|news|headlines)\b",
                re.IGNORECASE,
            ),
            "APP_CONTROL": re.compile(
                r"\b(open|launch|start|close|quit|run)\s+(?:the\s+|my\s+)?"
                r"(vs\s*code|vscode|calculator|notepad|terminal|app|application|"
                r"editor|explorer|settings|camera|[a-z]+\s+app)\b",
                re.IGNORECASE,
            ),
            "DEVELOPER_HELP": re.compile(
                r"\b(debug|error|compile|build|npm|pip|git|git status|webpack|vite|"
                r"cors|middleware|bug|traceback|line)\b",
                re.IGNORECASE,
            ),
            "EMOTIONAL": re.compile(
                r"\b(sad|stressed|overwhelmed|tired|stupid|impossible|give up|hate|"
                r"upset|angry|sigh)\b",
                re.IGNORECASE,
            ),
            "RESEARCH": re.compile(
                r"\b(research|compare|difference between|versus|vs|how does|why is)\b",
                re.IGNORECASE,
            ),
        }

    def analyze(self, user_prompt: str) -> str:
        """
        Analyzes the prompt and returns a standardized intent category string.
        Defaults to 'EXPLANATION' if no specific category matches.
        """
        prompt_clean = user_prompt.strip()
        if not prompt_clean:
            return "CONVERSATION"

        # Pure social turns first (strict patterns only — a command that merely
        # starts with "thanks"/"hey" must keep its action intent).
        if self._conversation_fullmatch.match(prompt_clean):
            return "CONVERSATION"
        if self._conversation_smalltalk.match(prompt_clean):
            return "CONVERSATION"

        # Check action regex matches in priority order
        for intent, pattern in self._patterns.items():
            if pattern.search(prompt_clean):
                return intent

        return "EXPLANATION"

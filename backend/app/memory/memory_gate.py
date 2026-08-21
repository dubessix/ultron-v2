"""
Ultron Core Memory Gate
Analyzes prompt complexity and skips semantic vector indexing for low-density requests (Greetings/Thanks).
Loads list triggers dynamically from config.yaml.
"""

import re
import yaml

from backend.app.install_paths import CONFIG_PATH

class MemoryGate:
    def __init__(self) -> None:
        self._greetings = self._load_regex_from_config()

    def _load_regex_from_config(self) -> re.Pattern:
        """Loads greeting list dynamically from config.yaml and compiles standard pattern."""
        default_words = ["hi", "hello", "hey", "thanks", "thank you", "welcome", "test"]
        
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f)
                    default_words = config.get("memory", {}).get("low_density_keywords", default_words)
            except Exception:
                pass

        # Escape keywords to build secure regex
        escaped_words = [re.escape(word) for word in default_words]
        pattern_str = r"^\b(" + "|".join(escaped_words) + r")\b[!?.]*$"
        return re.compile(pattern_str, re.IGNORECASE)

    def is_semantically_dense(self, user_prompt: str) -> bool:
        """
        Analyzes prompt contents. Returns False if query is a simple greeting/phrase,
        bypassing costly Cloud Embedding API execution.
        """
        clean = user_prompt.strip()
        if not clean:
            return False
            
        # If matches simple greeting pattern and has less than 4 words, mark as low density
        word_count = len(clean.split())
        if self._greetings.search(clean) and word_count < 4:
            return False
            
        return True

    # Patterns for token-saving decisions (recall/save gating)
    _RECALL_HINTS = re.compile(
        r"\b(remember|recall|previous|earlier|before|last time|what did i|what did we|"
        r"what happened|you told|we discussed|we decided|my project|our plan|"
        r"you said|we were|context|from before|what was|what is my name|"
        r"who am i|my goal|our stack|what are we building)\b",
        re.IGNORECASE,
    )

    # Human-like "calendar" recall: only when the user asks about the past.
    _TIME_AWARE_HINTS = re.compile(
        r"\b(yesterday|last (day|week|month|night)|3 days|three days|a few days|"
        r"earlier|previously|before|past few|last few|recently|the other day|"
        r"last time we|when did we|how long ago)\b",
        re.IGNORECASE,
    )

    _SAVE_HINTS = re.compile(
        r"\b(project|saas|app|build|build it|create|we should|our goal|"
        r"let'?s|tech stack|database|api|backend|frontend|feature|decision|"
        r"plan|roadmap|remember|keep in mind|important|i want|i will|"
        r"start|deploy|launch)\b",
        re.IGNORECASE,
    )

    def should_recall(self, user_prompt: str) -> bool:
        """
        Token saver: only trigger embedding recall for genuinely memory-related
        questions. Ordinary chatter / simple commands skip the (paid) embedding
        API entirely, so no tokens burn on everyday conversation.
        """
        clean = user_prompt.strip()
        if not clean or not self.is_semantically_dense(clean):
            return False
        # Trigger recall on direct memory questions OR past-time references.
        return bool(self._RECALL_HINTS.search(clean)) or bool(self._TIME_AWARE_HINTS.search(clean))

    def should_save(self, user_prompt: str) -> bool:
        """
        Token saver: only persist important turns (project decisions, goals, plans,
        tech stack) into long-term memory. Casual chatter is skipped so we don't
        spend embedding tokens (and storage) on trivial talk.
        """
        clean = user_prompt.strip()
        if not clean or not self.is_semantically_dense(clean):
            return False
        return bool(self._SAVE_HINTS.search(clean))

"""
Ultron Core Decision Engine
Routes requests to the optimal processing path: Fast (Direct), Medium (Single Tool), or Heavy (Orchestration).

Phase 0.B: the track is a latency/provider hint only. It no longer decides
whether the LLM receives tools — every non-conversational turn is armed and the
model chooses via native function calling.
"""

# Everyday Jarvis action domains -> single-tool "medium" path.
ACTION_INTENTS = frozenset({
    "DEVELOPER_HELP",
    "PLANNING",
    "EMOTIONAL",
    "WEATHER",
    "MUSIC",
    "SYSTEM",
    "FILE_OPS",
    "BROWSER",
    "SEARCH",
    "APP_CONTROL",
})


class DecisionEngine:
    def __init__(self) -> None:
        pass

    def get_speed_track(self, intent: str, confidence: float) -> str:
        """
        Determines processing speed track based on intent and confidence.
        Returns 'fast', 'medium', or 'heavy'.
        """
        # Low confidence requires Heavy Path to handle clarifying questions
        if confidence < 0.60:
            return "heavy"

        if intent in ("CONVERSATION", "EXPLANATION"):
            return "fast"

        if intent in ACTION_INTENTS:
            return "medium"

        if intent == "RESEARCH":
            return "heavy"

        return "fast"

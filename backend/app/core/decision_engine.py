"""
Ultron Core Decision Engine
Routes requests to the optimal processing path: Fast (Direct), Medium (Single Tool), or Heavy (Orchestration).
"""

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

        # Map intents to logical tracks
        if intent == "CONVERSATION":
            return "fast"
            
        elif intent == "EXPLANATION":
            return "fast"
            
        elif intent in ["DEVELOPER_HELP", "PLANNING", "EMOTIONAL"]:
            return "medium"
            
        elif intent == "RESEARCH":
            return "heavy"
            
        return "fast"

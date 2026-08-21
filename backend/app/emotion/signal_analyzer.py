"""
Ultron Extensible Signal Analyzer
Implements an Open/Closed Principle (OCP) compliant emotion and stress calculation suite.
Individual stress indicators inherit from BaseEmotionSignal and are compiled dynamically.
"""

from abc import ABC, abstractmethod
from typing import Dict

class BaseEmotionSignal(ABC):
    def __init__(self, weight: float) -> None:
        self.weight = weight

    @abstractmethod
    def evaluate(self, **kwargs) -> float:
        """Evaluates signal contribution. Returns a value normalized between 0.0 and 1.0."""
        pass

# --- Concrete Signals (OCP Compliant implementations) ---

class CompileErrorSignal(BaseEmotionSignal):
    def __init__(self) -> None:
        super().__init__(weight=0.3)

    def evaluate(self, **kwargs) -> float:
        consecutive_errors = kwargs.get("consecutive_errors", 0)
        # Max 4 errors maps to 1.0
        return min(1.0, consecutive_errors / 4.0)

class LateNightSignal(BaseEmotionSignal):
    def __init__(self) -> None:
        super().__init__(weight=0.2)

    def evaluate(self, **kwargs) -> float:
        current_hour = kwargs.get("current_hour", 12)
        if current_hour >= 23:  # 11 PM to Midnight
            return 0.5 + ((current_hour - 23) * 0.16)
        elif current_hour < 4:  # Midnight to 4 AM
            return 1.0 - (current_hour * 0.25)
        return 0.0

class DeleteRatioSignal(BaseEmotionSignal):
    def __init__(self) -> None:
        super().__init__(weight=0.2)

    def evaluate(self, **kwargs) -> float:
        delete_ratio = kwargs.get("delete_ratio", 0.0)
        return min(1.0, delete_ratio)

class SentimentSignal(BaseEmotionSignal):
    def __init__(self) -> None:
        super().__init__(weight=0.3)
        self._negative_keywords = [
            "hate", "broken", "impossible", "give up", "nothing works",
            "stupid", "annoying", "garbage", "trash", "slow", "fail", "error", "crash"
        ]

    def evaluate(self, **kwargs) -> float:
        user_prompt = kwargs.get("user_prompt", "").lower()
        matched_count = sum(1 for word in self._negative_keywords if word in user_prompt)
        # 3+ negative keywords yields maximum score of 1.0
        return min(1.0, matched_count / 3.0)

# --- Central Analyzer ---

class SignalAnalyzer:
    def __init__(self) -> None:
        # Dictionary of registered signals
        self._signals: Dict[str, BaseEmotionSignal] = {
            "compile_errors": CompileErrorSignal(),
            "late_night": LateNightSignal(),
            "delete_ratio": DeleteRatioSignal(),
            "sentiment": SentimentSignal()
        }

    def register_signal(self, name: str, signal: BaseEmotionSignal) -> None:
        """Register a new emotional indicator dynamically (OCP compliant)."""
        self._signals[name] = signal

    def calculate_stress_score(
        self,
        user_prompt: str,
        consecutive_errors: int,
        current_hour: int,
        delete_ratio: float
    ) -> float:
        """
        Calculates stress score dynamically by summing registered signals.
        Returns a float normalized between 0.0 and 1.0.
        """
        payload = {
            "user_prompt": user_prompt,
            "consecutive_errors": consecutive_errors,
            "current_hour": current_hour,
            "delete_ratio": delete_ratio
        }

        total_weight = sum(signal.weight for signal in self._signals.values())
        if total_weight == 0:
            return 0.0

        weighted_score = 0.0
        for signal in self._signals.values():
            contribution = signal.evaluate(**payload)
            weighted_score += signal.weight * contribution

        # Normalize score against total combined weights
        return float(max(0.0, min(1.0, weighted_score / total_weight)))

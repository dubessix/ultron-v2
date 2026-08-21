"""
Ultron Zora Trigger Orchestrator
Evaluates cumulative Stress Scores (Es) against dynamic configuration thresholds.
"""

import yaml
from typing import Tuple, Optional
from backend.app.emotion.signal_analyzer import SignalAnalyzer
from backend.app.install_paths import CONFIG_PATH

class ZoraTrigger:
    def __init__(self, analyzer: Optional[SignalAnalyzer] = None) -> None:
        self.analyzer = analyzer or SignalAnalyzer()
        self.threshold = self._load_threshold_from_config()

    def _load_threshold_from_config(self) -> float:
        """Loads trigger thresholds from config.yaml safely."""
        if not CONFIG_PATH.exists():
            return 0.75
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
                return config.get("personalities", {}).get("stress_threshold", 0.75)
        except Exception:
            return 0.75

    def evaluate_handoff(
        self,
        user_prompt: str,
        consecutive_errors: int,
        current_hour: int,
        delete_ratio: float
    ) -> Tuple[bool, float]:
        """
        Evaluates the active stress score.
        Returns a tuple: (should_handoff: bool, stress_score: float)
        """
        stress_score = self.analyzer.calculate_stress_score(
            user_prompt=user_prompt,
            consecutive_errors=consecutive_errors,
            current_hour=current_hour,
            delete_ratio=delete_ratio
        )
        
        return (stress_score >= self.threshold, stress_score)

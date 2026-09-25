"""
Ultron Personality State & Coordination Engine
Manages active personality lifecycles, manual switches, and automatic returns to Ultron.
"""

import yaml
import datetime
from typing import Dict, Optional
from pydantic import BaseModel, Field

from backend.app.personalities.base_personality import (
    BasePersonality,
    UltronPersonality,
    ZoraPersonality
)
from backend.app.install_paths import CONFIG_PATH

class PersonalityState(BaseModel):
    active_personality: str = Field("ultron", description="ID of the current active personality.")
    switch_reason: str = Field("System initialization", description="Reason for the active switch.")
    switch_type: str = Field("system", description="Switch type: manual | automatic | auto_return | system.")
    switched_at: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat(),
        description="UTC Timestamp of the active transition."
    )

class PersonalityEngine:
    def __init__(self, cooldown_turns: Optional[int] = None) -> None:
        # Read cooldown_turns from config.yaml when not explicitly provided,
        # so the runtime behavior stays in sync with configuration.
        self.cooldown_turns = cooldown_turns if cooldown_turns is not None else self._load_cooldown_from_config()
        
        # State tracking
        self.state = PersonalityState()
        self._zora_active_turns = 0
        
        # Registry of supported personalities (OCP compliant)
        self._registry: Dict[str, BasePersonality] = {
            "ultron": UltronPersonality(),
            "zora": ZoraPersonality()
        }

        # No name-matching word lists: the AI decides a switch with switch_mode
        # (core/control_tools.py); the UI toggle calls update_state directly.

    @staticmethod
    def _load_cooldown_from_config() -> int:
        """Reads cooldown_turns from config.yaml safely (default 3)."""
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f)
                    return int(config.get("personalities", {}).get("cooldown_turns", 3))
            except Exception:
                pass
        return 3

    def register_personality(self, personality: BasePersonality) -> None:
        """Register a new personality dynamically (Supports Open/Closed Principle)."""
        self._registry[personality.id] = personality

    def get_personality(self, personality_id: str) -> BasePersonality:
        """Extracts a registered personality object."""
        if personality_id not in self._registry:
            # Fallback to Ultron to prevent crashes
            return self._registry["ultron"]
        return self._registry[personality_id]

    def update_state(self, personality: str, reason: str, switch_type: str) -> None:
        """Performs atomic state transition and resets transaction metrics."""
        self.state = PersonalityState(
            active_personality=personality,
            switch_reason=reason,
            switch_type=switch_type,
            switched_at=datetime.datetime.now(datetime.timezone.utc).isoformat()
        )
        # Reset the Zora active-turn counter on any transition.
        self._zora_active_turns = 0

    def increment_zora_lifecycle(self) -> Optional[PersonalityState]:
        """
        Monitors Zora's active emotional overlay duration.
        If turns exceed self.cooldown_turns, automatically transitions state back to Ultron (Auto Return).
        """
        if self.state.active_personality != "zora":
            return None
        # The owner chose Zora himself (button, voice, "switch to Zora", or a
        # restored session): she stays until he switches back. Only a stress-
        # triggered automatic handoff returns to Ultron by itself.
        if self.state.switch_type != "automatic":
            return None

        self._zora_active_turns += 1
        if self._zora_active_turns >= self.cooldown_turns:
            print(f"[PERSONALITY_ENGINE] Zora emotional intervention complete ({self._zora_active_turns} turns). Returning to Ultron.")
            self.update_state(
                personality="ultron",
                reason="Auto-return: Emotional intervention complete.",
                switch_type="auto_return"
            )
            return self.state
        return None


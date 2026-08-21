"""
Ultron Security Permission Manager
Coordinates system permission levels and verifies tool execution boundaries.
"""


class PermissionManager:
    def __init__(self) -> None:
        self.levels = {
            0: "Read-Only (No Confirmation)",
            1: "Write (No Confirmation)",
            2: "System Commands (Requires Manual Confirmation)",
            3: "Dangerous/Destructive (Requires Manual Confirmation)"
        }

    def requires_manual_confirmation(self, permission_level: int) -> bool:
        """Returns True if the tool's security level demands user confirmation before execution."""
        return permission_level >= 2

"""
Ultron Security Confirmation Gate Interceptor
Intercepts level 2/3 execution requests and enforces explicit user confirmation.
"""

from typing import Dict, Any, Optional
from backend.app.security.permission_manager import PermissionManager

class ConfirmationGate:
    def __init__(self, manager: Optional[PermissionManager] = None) -> None:
        self.manager = manager or PermissionManager()

    def inspect_and_authorize(
        self,
        tool_id: str,
        permission_level: int,
        has_confirmed: bool = False
    ) -> Dict[str, Any]:
        """
        Inspects the tool's required permission level.
        If it requires manual confirmation and user has not confirmed yet,
        returns a PENDING_CONFIRMATION response to halt execution.
        """
        if self.manager.requires_manual_confirmation(permission_level) and not has_confirmed:
            print(f"[SECURITY_GATE] Intercepted Level {permission_level} tool: '{tool_id}'. Awaiting manual user authorization.")
            return {
                "status": "PENDING_CONFIRMATION",
                "tool_id": tool_id,
                "message": f"Tool '{tool_id}' requires manual confirmation for execution.",
                "required_permission_level": permission_level
            }
            
        return {
            "status": "APPROVED"
        }

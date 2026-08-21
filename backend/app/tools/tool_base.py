"""
Ultron Core Tool Base Class Abstraction
Defines the abstract interface for all local and system automation tools.
Enforces strict Pydantic-based input argument validation schemas and standardized ToolResult structures.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Type, List, Optional
from pydantic import BaseModel, Field

# --- Standardized Tool Result Pydantic Model (Requirement 4) ---

class ToolResult(BaseModel):
    success: bool = Field(..., description="Flags whether tool execution was successful.")
    data: Dict[str, Any] = Field(default_factory=dict, description="Execution success data payload.")
    error: Optional[str] = Field(None, description="Detailed error description string in case of failures.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Standard metrics (execution_time_ms, tool_name).")

# --- Base Tool Abstract Class (Requirement 2) ---

class BaseTool(ABC):
    def __init__(
        self,
        tool_id: str,
        name: str,
        description: str,
        category: str,
        tags: List[str],
        permission_level: int,
        args_model: Type[BaseModel],
        usage_examples: List[str]
    ) -> None:
        self.id = tool_id
        self.name = name
        self.description = description
        self.category = category
        self.tags = tags
        # Security Levels: 0 (Read-Only) | 1 (Write) | 2 (System) | 3 (Dangerous)
        self.permission_level = permission_level
        self.args_model = args_model
        self.usage_examples = usage_examples

    def permission_for_arguments(self, arguments: Dict[str, Any]) -> int:
        """Allow tools with mixed read/write actions to raise permission dynamically."""
        return self.permission_level

    def get_metadata(self) -> Dict[str, Any]:
        """Extracts complete tool metadata, useful for dynamic LLM context matching."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "tags": self.tags,
            "permission_level": self.permission_level,
            "input_schema": self.args_model.model_json_schema(),
            "usage_examples": self.usage_examples
        }

    @abstractmethod
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Executes the tool's core logic asynchronously after arguments are validated.
        Returns a raw dictionary response payload (wrapped inside ToolResult by the Registry).
        """
        pass

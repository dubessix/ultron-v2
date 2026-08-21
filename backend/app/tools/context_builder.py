"""
Ultron Tool Context Builder
Selects and filters relevant tools based on user prompt context, minimizing LLM token waste.
Satisfies SOLID, KISS, and Clean Architecture standards.
"""

import json
from typing import List
from backend.app.tools.tool_base import BaseTool

class ToolContextBuilder:
    def __init__(self) -> None:
        pass

    def filter_relevant_tools(self, user_prompt: str, registered_tools: List[BaseTool]) -> List[BaseTool]:
        """
        Heuristically filters registered tools by scanning prompt keywords against tool tags, names, and descriptions.
        If the prompt is generic, limits metadata injection to avoid token waste.
        """
        clean_prompt = user_prompt.lower()
        
        # If the user prompt is extremely short or generic conversational greetings, return empty list
        if len(clean_prompt.split()) < 3 and any(word in clean_prompt for word in ["hi", "hello", "hey", "thanks"]):
            return []

        relevant_tools = []
        for tool in registered_tools:
            # Match keywords inside tool ID, tags, name, or description
            matched = False
            if tool.id in clean_prompt or tool.category.lower() in clean_prompt:
                matched = True
            else:
                for tag in tool.tags:
                    if tag.lower() in clean_prompt:
                        matched = True
                        break
                        
            if matched:
                relevant_tools.append(tool)

        # Fallback: If no specific tools matched but prompt is technical, inject all non-dangerous tools
        if not relevant_tools and any(word in clean_prompt for word in ["file", "run", "code", "terminal", "write", "read"]):
            # Filter out level 3 dangerous tools to protect system bounds
            relevant_tools = [t for t in registered_tools if t.permission_level < 3]

        return relevant_tools

    def build_system_prompt_fragment(self, relevant_tools: List[BaseTool]) -> str:
        """Assembles a clean, structured system prompt fragment of only selected tool schemas."""
        if not relevant_tools:
            return "No local tools are currently required for this conversational exchange."

        fragment = "You have access to the following local system tools:\n\n"
        for tool in relevant_tools:
            meta = tool.get_metadata()
            fragment += (
                f"- Tool ID: {meta['id']}\n"
                f"  Name: {meta['name']}\n"
                f"  Description: {meta['description']}\n"
                f"  Permission Level: {meta['permission_level']}\n"
                f"  Input Schema: {json.dumps(meta['input_schema']['properties'])}\n"
                f"  Usage Examples: {', '.join(meta['usage_examples'])}\n\n"
            )
        return fragment

"""Tiny helper for tests: a scripted AI brain (the AI decides, tests script it)."""

from __future__ import annotations

import json
from contextlib import contextmanager


def reply(content="", calls=None):
    return {"content": content, "tool_calls": calls or [], "provider": "groq", "model": "fake",
            "native_tools": True, "provider_state": None}


def use(tool, args, call_id="c1"):
    return {"id": call_id, "name": "use_tool", "arguments": {"tool": tool, "arguments_json": json.dumps(args)}}


def call(name, args, call_id="c1"):
    return {"id": call_id, "name": name, "arguments": args}


@contextmanager
def scripted_brain(orchestrator, script):
    """script(user_prompt, conversation) -> reply(...). Records every brain call."""
    calls = []

    async def brain(system_prompt, user_prompt, tools, conversation=None, **kwargs):
        conv = conversation or []
        calls.append({"system": system_prompt, "user": user_prompt, "conv": conv,
                      "tools": [t.get("tool_id") for t in tools], **kwargs})
        return script(user_prompt, conv)

    original = orchestrator.router.get_completions_with_tools
    orchestrator.router.get_completions_with_tools = brain
    try:
        yield calls
    finally:
        orchestrator.router.get_completions_with_tools = original

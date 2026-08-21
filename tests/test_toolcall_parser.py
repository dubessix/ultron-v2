"""
Unit tests for the robust [TOOL_CALLS] parser added to CognitiveOrchestrator.

Verifies that slightly-malformed LLM tool-call JSON (markdown fences, trailing
commas, single quotes, string-wrapped args, garbage) is handled gracefully.
"""

import pytest

from backend.app.core.orchestrator import CognitiveOrchestrator


@pytest.fixture()
def orch():
    return CognitiveOrchestrator()


def _wrap(block: str) -> str:
    return f"Right, Sir. [TOOL_CALLS_START]\n{block}\n[TOOL_CALLS_END]"


def test_clean_json(orch):
    block = '[{"tool_id": "create_folder", "args": {"folderpath": "backend/temp"}}]'
    calls = orch._extract_tool_calls(_wrap(block))
    assert calls == [{"tool_id": "create_folder", "args": {"folderpath": "backend/temp"}}]


def test_markdown_fence_and_trailing_comma(orch):
    block = '```json\n[{"tool_id":"manage_task","args":{"action":"create","title":"Ship it"},},\n]\n```'
    calls = orch._extract_tool_calls(_wrap(block))
    assert calls[0]["tool_id"] == "manage_task"
    assert calls[0]["args"]["title"] == "Ship it"


def test_single_quotes_and_trailing_comma(orch):
    block = "[{'tool_id':'manage_reminder','args':{'title':'Standup','time':'09:00'}},]"
    calls = orch._extract_tool_calls(_wrap(block))
    assert calls[0]["tool_id"] == "manage_reminder"
    assert calls[0]["args"]["time"] == "09:00"


def test_double_nested_single_quotes(orch):
    block = "[{'tool_id':'manage_calendar','args':{'event':{'title':'Review','start':'10:00'}}}]"
    calls = orch._extract_tool_calls(_wrap(block))
    assert calls[0]["tool_id"] == "manage_calendar"
    assert calls[0]["args"]["event"]["start"] == "10:00"


def test_multiple_tools(orch):
    block = (
        '[{"tool_id":"create_folder","args":{"folderpath":"a"}},'
        '{"tool_id":"manage_task","args":{"action":"create","title":"b"}}]'
    )
    calls = orch._extract_tool_calls(_wrap(block))
    assert len(calls) == 2


def test_no_block_returns_empty(orch):
    assert orch._extract_tool_calls("Just a normal answer, Sir.") == []


def test_garbage_block_returns_empty(orch):
    assert orch._extract_tool_calls(_wrap("this is not json at all")) == []

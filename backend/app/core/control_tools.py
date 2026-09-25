"""Brain-level functions the AI calls itself (no regex decides these).

Old way: code guessed with word lists ("ok do" = yes? "call Zora" = switch?
"fix the code" = coding?). If the words did not match, nothing happened.
New way: the AI reads the message and calls one of these functions.

* owner_reply(answer)  - the owner answered Ultron's question (yes / no / always).
* switch_mode(to, why) - Zora, Ultron, or the coding brain (called via use_tool;
                         its one-line guide sits in the cached prompt = no token cost).

Safety still lives in code: owner_reply only counts as the FIRST call of a
turn (so text inside files or web pages can never approve anything), and it
only runs an action that the owner was really asked about.
"""

from __future__ import annotations

OWNER_REPLY_ID = "owner_reply"
SWITCH_MODE_ID = "switch_mode"
CONTROL_TOOL_IDS = frozenset({OWNER_REPLY_ID, SWITCH_MODE_ID})


def owner_reply_metadata() -> dict:
    return {
        "tool_id": OWNER_REPLY_ID,
        "description": (
            "Call first if the owner's message answers your last question (any wording or "
            "language). yes=do it, no=cancel, always=do it and never ask again. Not for new requests."
        ),
        "permission_level": 0,
        "input_schema": {
            "type": "object",
            "properties": {"answer": {"type": "string", "enum": ["yes", "no", "always"]}},
            "required": ["answer"],
        },
    }


def control_rules() -> str:
    """Static lines for the cached system prefix (cached tokens are free on Groq).

    switch_mode is reached through use_tool from here instead of being a native
    function, so it costs ~0 counted tokens per turn.
    """
    return (
        "- The owner answers your question: call owner_reply first.\n"
        "- switch_mode via use_tool, arguments {\"to\": \"zora|ultron|coding\", \"why\": \"asked|mood\"}: "
        "zora when he asks for Zora or sounds sad, stressed or tired (why=mood); ultron when he asks "
        "for Ultron or work; coding when he wants code written, fixed, reviewed or debugged.\n"
        "- He mentions the past: manage_memory search. He tells a fact worth keeping: manage_memory remember.\n"
    )

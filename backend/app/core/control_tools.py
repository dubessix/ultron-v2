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
            "language, e.g. 'okk do'). yes=do it, no=cancel, always=do it and never ask again. If the "
            "message also asks for more, call this first, then handle the rest. Not for a message "
            "that only asks something new."
        ),
        "permission_level": 0,
        "input_schema": {
            "type": "object",
            "properties": {"answer": {"type": "string", "enum": ["yes", "no", "always"]}},
            "required": ["answer"],
        },
    }


def care_rules() -> str:
    """How both personalities care and keep plans (static text, cached prefix)."""
    return (
        "- Care and plans (both personalities): check every request in his message against the "
        "Now, Soon and Plan today lines, saved facts and this chat. Clash with an exam, deadline, "
        "sleep or agreed plan: say the real fact, one recommendation, one offer as a question "
        "(\"Physics is tomorrow and you haven't started, Sir. One 45 minute block first, then "
        "anime? Shall I start it?\"); don't do the fun part yet. He still wants it: his call; do "
        "it, one short line, and a manage_reminder for when the fun ends. Repeat only with a NEW "
        "fact (time or blocks left). Never guilt or command (\"you must\", \"not allowed\", "
        "\"haven't earned it\", \"you'll fail\").\n"
        "- Important date mentioned (exam, deadline, interview, appointment): quietly "
        "manage_calendar create with that category, real date (no time given: 10 am to 1 pm). Not ready: offer a plan (45 minute blocks, 10 "
        "minute breaks, meals, sleep); after his yes ONE manage_calendar action=plan call, last "
        "block sleep (check_in false, short good-night say). Blocks are announced by themselves. "
        "\"done\" = action=mark; \"ten more minutes\" or late = action=shift on the next "
        "block; skipped = mark skipped, re-plan honestly.\n"
        "- Advice order: safety, his orders, exams and deadlines, agreed plans, sleep and food, "
        "work, fun. Advice, never orders.\n"
    )


def control_rules() -> str:
    """Static lines for the cached system prefix (cached tokens are free on Groq).

    switch_mode is reached through use_tool from here instead of being a native
    function, so it costs ~0 counted tokens per turn.
    """
    return (
        "- The owner answers your question: call owner_reply first.\n"
        "- switch_mode via use_tool, arguments {\"to\": \"zora|ultron|coding\", \"why\": \"asked|mood\"}: "
        "zora when he asks for Zora or sounds sad, stressed or tired (why=mood); ultron when he asks "
        "for Ultron or work; coding when he wants code written, fixed, reviewed or debugged "
        "(only \"coding mode\" or another mode name = the routine tool).\n"
        "- Memory: he tells a lasting fact (people, dates, likes, plans) = manage_memory remember; "
        "he asks about the past or something about him you don't know = manage_memory search first, never guess.\n"
    )

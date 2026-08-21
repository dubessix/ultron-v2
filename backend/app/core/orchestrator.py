"""
Ultron Core Cognitive Orchestrator
Coordinates the entire request processing lifecycle from raw text inputs to final LLM response streams.
Integrates Intent Analysis, Confidence Check, Speed Path Decision, Memory Syncing, Personalities,
Structured AI Actions, and Parallel LLM-driven Tool Calling.
"""

import time
import sys
import uuid
import json
import re
import datetime
import asyncio
from typing import Dict, Any, Optional, List

from backend.app.core.intent_analyzer import IntentAnalyzer
from backend.app.core.confidence_engine import ConfidenceEngine
from backend.app.core.decision_engine import DecisionEngine
from backend.app.memory.memory_engine import MemoryEngine
from backend.app.brain.llm_router import LLMRouter
from backend.app.personalities.personality_engine import PersonalityEngine
from backend.app.emotion.zora_trigger import ZoraTrigger
from backend.app.tools.tool_registry import ToolRegistry

# Shared module-level coding-mode flag. New CognitiveOrchestrator instances read
# this as their default, so a manual toggle in one request persists across all
# subsequent chat requests (which each construct their own orchestrator).
_SHARED_CODING_MODE = False

class CognitiveOrchestrator:
    def __init__(
        self,
        intent_analyzer: Optional[IntentAnalyzer] = None,
        confidence_engine: Optional[ConfidenceEngine] = None,
        decision_engine: Optional[DecisionEngine] = None,
        memory_engine: Optional[MemoryEngine] = None,
        llm_router: Optional[LLMRouter] = None,
        personality_engine: Optional[PersonalityEngine] = None,
        zora_trigger: Optional[ZoraTrigger] = None
    ) -> None:
        self.intent_analyzer = intent_analyzer or IntentAnalyzer()
        self.confidence_engine = confidence_engine or ConfidenceEngine()
        self.decision_engine = decision_engine or DecisionEngine()
        self.memory = memory_engine or MemoryEngine()
        self.router = llm_router or LLMRouter()
        self.personalities = personality_engine or PersonalityEngine()
        self.zora_trigger = zora_trigger or ZoraTrigger()
        
        # Coding Mode state
        # - manual: toggled by the user (on/off) — SHARED module-level so it persists
        # - auto: a CODING intent triggers NVIDIA coding provider automatically
        self.coding_mode: bool = _SHARED_CODING_MODE
        self.coding_manual_override: bool = _SHARED_CODING_MODE
        self.coding_auto_detect: bool = True
        self.max_coding_steps: int = 8  # bound multi-file tasks to prevent runaway loops
        
        # Local event tracking array
        self.dispatched_events: List[Dict[str, Any]] = []
        # Existing files must be read successfully before a coding write. Store a
        # fingerprint so a changed-on-disk file must be inspected again.
        self._coding_inspections: Dict[str, Dict[str, str]] = {}
        # The personality/event engine is process-shared. Serialize turns so two
        # concurrent transports cannot clear or overwrite each other's state.
        self._request_lock = asyncio.Lock()

    def set_coding_mode(self, enabled: bool) -> None:
        """Manually toggle coding mode.

        - enabled=True  -> arm NVIDIA coding (CODING intents use NVIDIA). Persists globally.
        - enabled=False -> disarm coding (all turns use Groq). Persists globally.
        Either way, NVIDIA is only ever used on CODING intents — never on normal chat.
        """
        global _SHARED_CODING_MODE
        self.coding_auto_detect = bool(enabled)
        self.coding_mode = bool(enabled)
        _SHARED_CODING_MODE = bool(enabled)
        print(f"[COGNITIVE_ORCHESTRATOR] Coding mode {'ON (armed)' if enabled else 'OFF'}.")

    def _should_use_coding_provider(self, intent: str, user_prompt: str) -> bool:
        """True if this turn should use the NVIDIA coding provider.

        NVIDIA is reserved for CODING turns only. Reads the SHARED global flag so a
        manual coding-mode toggle (from any endpoint) takes effect on the shared
        brain too. Normal conversation NEVER routes to NVIDIA — saving its limit
        for coding.
        """
        # Manual ON forces NVIDIA for all turns; otherwise only CODING intents use it.
        if _SHARED_CODING_MODE:
            return True
        return intent == "CODING"

    def _dispatch_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Publishes structured personality/emotional event frameworks."""
        event = {
            "event_id": str(uuid.uuid4()),
            "type": event_type,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "payload": payload
        }
        self.dispatched_events.append(event)
        print(f"[EVENT_BUS] Published event: {event_type} -> {payload}")

    def _dispatch_log(self, level: str, message: str) -> None:
        """Emit a real-time operational log line (shown in the UI Log tab)."""
        self.dispatched_events.append({
            "event_id": str(uuid.uuid4()),
            "type": "log",
            "log": {"level": level, "message": message},
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
        })

    async def _tool_live_messages(self, tool_id: str, args: dict, result: dict) -> list:
        """Jarvis-style live narration for a tool, generated by the LLM from REAL data.
        Each call produces varied, natural wording (not the same line every time),
        so it feels genuinely alive. Falls back to a brief template if the LLM fails."""
        lines = []
        tool_hint = {
            "find_files": "searching the project for files",
            "search_inside_documents": "searching inside your documents",
            "google_search": "searching the web",
            "github_search": "searching GitHub",
            "weather_tool": "checking the live weather",
            "system_metrics": "reading your system telemetry",
            "file_write": "writing a file",
            "create_folder": "organizing folders",
            "organize_folder": "organizing your folders",
            "terminal_run": "running a command",
            "tavily_research": "researching the web",
            "git_status": "reading the repository state",
            "manage_task": "managing your tasks",
            "manage_reminder": "handling your reminder",
            "manage_calendar": "updating your calendar",
        }.get(tool_id, f"executing {tool_id}")

        try:
            import json as _json
            data_snippet = _json.dumps(result, default=str)[:300]
            prompt = (
                f"You are Jarvis speaking live. The tool '{tool_id}' ({tool_hint}) just finished. "
                f"Real result: {data_snippet}\n"
                "Reply with ONE short, warm line (8-16 words) as Jarvis telling the user what "
                "just happened, varied each time (don't repeat the same wording). No emojis, no quotes."
            )
            narration = await self.router.get_completions(
                system_prompt="You are Jarvis, a warm human assistant. Be brief, varied, natural.",
                user_prompt=prompt,
                temperature=0.9,
                provider_preference="groq"
            )
            if narration and not narration.startswith("[Offline]") and narration.strip():
                lines.append(("info", narration.strip()))
                lines.append(("success", "Done."))
                return lines
        except Exception:
            pass
        # Fallback (brief, varied enough)
        lines.append(("info", f"{tool_hint.capitalize()}..."))
        lines.append(("success", "Done."))
        return lines

    def _extract_tool_calls(self, text: str) -> List[Dict[str, Any]]:
        """
        Robustly extracts and parses the [TOOL_CALLS_START]...[TOOL_CALLS_END] block.
        Tolerates markdown code fences, surrounding text, trailing commas, and single vs
        double quotes so an LLM's slightly-off JSON still executes instead of silently failing.
        """
        match = re.search(
            r"\[TOOL_CALLS_START\](.*?)\[TOOL_CALLS_END\]",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if not match:
            return []

        block = match.group(1).strip()

        # Drop markdown code fences if the model wrapped the JSON (```json ... ```)
        block = re.sub(r"^```(?:json)?\s*", "", block, flags=re.IGNORECASE)
        block = re.sub(r"\s*```$", "", block)

        # Try strict JSON first; fall back to a tolerant normalizer on failure.
        try:
            return json.loads(block)
        except (json.JSONDecodeError, ValueError):
            pass

        # Tolerant pass: handle Python/JS-style single-quoted strings and trailing commas.
        tolerant = block
        # Convert balanced single-quoted strings ('foo' or 'foo bar') to double-quoted.
        tolerant = re.sub(
            r"'((?:[^'\\]|\\.)*)'",
            lambda m: '"' + m.group(1) + '"',
            tolerant,
        )
        # Strip trailing commas before closing brackets/braces.
        tolerant = re.sub(r",(\s*[\]}])", r"\1", tolerant)
        try:
            return json.loads(tolerant)
        except (json.JSONDecodeError, ValueError):
            return []

    def _compile_tools_metadata(self) -> str:
        """Collects descriptions and schema metrics from our registry dynamically (OCP compliant)."""
        registry = ToolRegistry()
        tools_list = registry.get_all_tools()
        meta = []
        for t in tools_list:
            schema = t.args_model.model_json_schema() if t.args_model else {}
            meta.append({
                "tool_id": t.id,
                "description": t.description,
                "arguments": list(schema.get("properties", {}).keys())
            })
        return json.dumps(meta, indent=2)

    def _scan_project_context(self, max_depth: int = 3) -> str:
        """
        Codex-style: scans the project root for structure so Ultron knows what it's
        working on (folders, key files, manifest). Returns a concise text summary.
        Deliberately bounded (shallow, capped) so it never hangs or bloats context.
        """
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent.parent.parent  # project root
        ignore = {".git", "node_modules", "__pycache__", ".cache", "dist", "build",
                  ".venv", "venv", "data", "uploads", "images"}
        lines = []
        stack = [(root, 0)]
        while stack:
            p, depth = stack.pop()
            if depth > max_depth:
                continue
            try:
                entries = sorted(p.iterdir(), key=lambda e: (e.is_dir(), e.name.lower()))
            except Exception:
                continue
            for e in entries:
                if e.name in ignore:
                    continue
                indent = "  " * depth
                if e.is_dir():
                    lines.append(f"{indent}[dir] {e.name}/")
                    stack.append((e, depth + 1))
                else:
                    # Only list a few notable manifest files to keep it small.
                    if e.name in ("config.yaml", "requirements.txt", "package.json",
                                  "setup.py", "README.md", "main.py", "app.py"):
                        lines.append(f"{indent}{e.name}")
        return "\n".join(lines[:120])

    async def _get_project_context_block(self, project_id: str = "personal") -> str:
        """Combine project-scoped stored state + live scan into a prompt block for coding.

        The directory scan runs in a worker thread (asyncio.to_thread) so a large
        project can never block the event loop and freeze the assistant.
        """
        parts = []
        # Stored project facts (name, stack, goals)
        stored = []
        for key in ("project_name", "tech_stack", "project_goal", "project_structure"):
            val = self.memory.project.get_project_state(f"{project_id}:{key}")
            if val is None and project_id == "personal":
                val = self.memory.project.get_project_state(key)  # legacy fallback
            if val:
                stored.append(f"{key}: {val}")
        if stored:
            parts.append("\n".join(stored))

        # Live structure scan — off the event loop.
        try:
            scan = await asyncio.to_thread(self._scan_project_context)
        except Exception as e:
            print(f"[COGNITIVE_ORCHESTRATOR] Warning: project scan failed: {e}")
            scan = ""
        if scan:
            parts.append("Current project structure (top-level):\n" + scan)

        if not parts:
            return ""
        return "\n\n[PROJECT_CONTEXT]\n" + "\n\n".join(parts)

    async def _recall_long_term_memory(
        self, user_prompt: str, force: bool = False, project_id: str = "personal"
    ) -> str:
        """
        Human-like long-term recall: queries episodic + semantic memory for the
        most relevant past events/concepts, returning a context block for the
        system prompt.

        Token-smart: by default it only recalls on memory/past-time questions
        (see memory_gate). When force=True (e.g. a coding turn), it does a light
        recall for project continuity across days. Always degrades gracefully.
        """
        try:
            # Token saver: skip embedding recall unless memory-related or forced.
            if not force and not self.memory.gate.should_recall(user_prompt):
                return ""

            # Query both memory layers in parallel (low latency, async/network-bound).
            past_events, past_concepts = await asyncio.gather(
                self.memory.episodic.recall_related_events(
                    user_prompt, limit=3, project_id=project_id
                ),
                self.memory.semantic.recall_related_concepts(
                    user_prompt, limit=3, project_id=project_id
                ),
            )

            blocks = []
            if past_events:
                snippets = []
                for item in past_events:
                    sim = item.get("similarity", 0.0)
                    if sim >= 0.45:
                        snippets.append(item["content"])
                if snippets:
                    blocks.append("Relevant past events from your sessions:\n" + "\n".join("- " + s for s in snippets))

            if past_concepts:
                snippets = []
                for item in past_concepts:
                    sim = item.get("similarity", 0.0)
                    if sim >= 0.45:
                        snippets.append(item["content"])
                if snippets:
                    blocks.append("Knowledge/concepts you previously taught me:\n" + "\n".join("- " + s for s in snippets))

            if not blocks:
                return ""
            return "\n\n[LONG_TERM_MEMORY]\n" + "\n\n".join(blocks) + "\n"
        except Exception as e:
            print(f"[COGNITIVE_ORCHESTRATOR] Warning: Long-term recall skipped: {e}")
            return ""

    async def _persist_turn_to_memory(
        self,
        user_prompt: str,
        ai_response: str,
        project_id: str = "personal",
        session_id: Optional[str] = None,
    ) -> None:
        """
        Persists a meaningful conversational turn into long-term episodic memory
        so Ultron "remembers" like Jarvis. Skips low-density greetings to avoid
        bloating the vector store, and is fully wrapped so it can never break the
        main conversation flow. Runs as a background task (non-blocking).
        """
        try:
            # Token saver: only persist important turns (project/decision/plans).
            if not self.memory.gate.should_save(user_prompt):
                return
            # Keep stored entries short & focused to conserve storage.
            entry = f"{user_prompt.strip()[:500]} -> {ai_response.strip()[:500]}"
            await self.memory.episodic.record_event(
                content=entry,
                metadata={
                    "kind": "conversation_turn",
                    "project_id": project_id,
                    "session_id": session_id,
                    "category": "episodic",
                    "importance": "normal",
                }
            )
        except Exception as e:
            print(f"[COGNITIVE_ORCHESTRATOR] Warning: Memory persist skipped: {e}")

    @staticmethod
    def _file_fingerprint(filepath: str) -> Optional[str]:
        from pathlib import Path
        import hashlib

        path = Path(filepath).expanduser().resolve(strict=False)
        if not path.is_file():
            return None
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return None

    def _mark_coding_inspection(self, session_id: str, filepath: str) -> None:
        fingerprint = self._file_fingerprint(filepath)
        if fingerprint:
            from pathlib import Path
            resolved = str(Path(filepath).expanduser().resolve(strict=False))
            self._coding_inspections.setdefault(session_id, {})[resolved] = fingerprint

    def _has_current_coding_inspection(self, session_id: str, filepath: str) -> bool:
        from pathlib import Path
        resolved = str(Path(filepath).expanduser().resolve(strict=False))
        expected = self._coding_inspections.get(session_id, {}).get(resolved)
        return bool(expected and expected == self._file_fingerprint(filepath))

    async def _coding_safe_write(
        self,
        args: Dict[str, Any],
        has_confirmed: bool = False,
        session_id: Optional[str] = None,
        confirmation_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Compatibility wrapper over the single validated ToolRegistry write path."""
        registry = ToolRegistry()
        return await registry.execute_tool(
            tool_id="file_write",
            args=args,
            has_confirmed=has_confirmed,
            confirmation_token=confirmation_token,
            session_id=session_id,
            max_retries=0,
        )

    async def _safe_verify_code(self, filepath: str) -> Dict[str, Any]:
        """
        Step C: safely verify a written file without risking the system.
        Runs ONLY a syntax check (python -m py_compile / node --check) with a
        hard timeout. Never executes arbitrary/destructive commands and never
        touches the whole system. Returns pass/fail + reason.
        """
        import asyncio as _asyncio
        from pathlib import Path
        result = {"file": filepath, "verified": False, "lang": None, "detail": None}
        path = Path(filepath)
        if not path.exists():
            result["detail"] = "file not found"
            return result

        if filepath.endswith(".py"):
            result["lang"] = "python"
            cmd = [sys.executable, "-m", "py_compile", filepath]
        elif filepath.endswith((".js", ".jsx", ".ts", ".tsx")):
            result["lang"] = "node"
            cmd = ["node", "--check", filepath]
        else:
            result["detail"] = "no safe syntax check available for this file type"
            return result

        try:
            proc = await _asyncio.create_subprocess_exec(
                *cmd,
                stdout=_asyncio.subprocess.PIPE,
                stderr=_asyncio.subprocess.PIPE,
            )
            try:
                _stdout, stderr = await _asyncio.wait_for(proc.communicate(), timeout=8.0)
            except _asyncio.TimeoutError:
                try:
                    proc.kill()
                except Exception:
                    pass
                result["detail"] = "verification timed out (cancelled to avoid hang)"
                return result
            result["verified"] = (proc.returncode == 0)
            result["detail"] = (stderr.decode("utf-8", "ignore").strip()
                                if proc.returncode != 0 else "syntax OK")
        except Exception as e:
            result["detail"] = f"verification failed to run: {e}"
        return result

    def _resolve_structured_action(self, user_prompt: str) -> Dict[str, Any]:
        """
        CONSTITUTIONAL DESIGN (Rule 8):
        Provides standard keyword matching fallback in case no tool calling is resolved by the LLM.
        """
        clean = user_prompt.lower()
        
        if "todo" in clean or "task" in clean:
            return {"action": "open_widget", "widget_id": "todo"}
        if "reminder" in clean or "alarm" in clean or "timer" in clean or "remind" in clean:
            return {"action": "open_widget", "widget_id": "reminder"}
        if "schedule" in clean or "calendar" in clean or "plan" in clean:
            return {"action": "open_widget", "widget_id": "calendar"}
        if "git" in clean or "branch" in clean:
            return {"action": "open_widget", "widget_id": "git"}
        if "drive" in clean or "downloads" in clean or "explorer" in clean or "folder" in clean or "find" in clean:
            return {"action": "open_widget", "widget_id": "file_explorer"}
        if "research" in clean:
            return {"action": "open_widget", "widget_id": "deep_research"}
        if "search" in clean:
            return {"action": "open_widget", "widget_id": "universal_search"}
        if "weather" in clean:
            return {"action": "open_widget", "widget_id": "weather"}
        if "stock" in clean or "bitcoin" in clean or "price" in clean or "market" in clean or "tesla" in clean:
            return {"action": "open_widget", "widget_id": "market"}
        if "terminal" in clean or "run" in clean or "process" in clean:
            return {"action": "open_widget", "widget_id": "terminal"}
        if "memory" in clean or "remember" in clean:
            return {"action": "open_widget", "widget_id": "memory"}
        if "notification" in clean or "alert" in clean:
            return {"action": "open_widget", "widget_id": "notification"}
        if "system" in clean or "cpu" in clean or "ram" in clean or "hardware" in clean:
            return {"action": "open_widget", "widget_id": "system"}
        if "optimize" in clean or "refactor" in clean or "quality" in clean:
            return {"action": "open_widget", "widget_id": "code_optimizer"}
        if "graph" in clean or "dependency" in clean or "caller" in clean or "semantic" in clean:
            return {"action": "open_widget", "widget_id": "semantic_code_graph"}
        if "security" in clean or "scan" in clean or "audit" in clean or "vulnerability" in clean:
            return {"action": "open_widget", "widget_id": "security_guardian"}
        if "morning" in clean or "briefing" in clean or "greeting" in clean:
            return {"action": "open_widget", "widget_id": "daily_briefing"}
            
        return {"action": "none"}

    async def process_request(
        self,
        user_prompt: str,
        session_id: str,
        project_id: str = "personal",
        consecutive_errors: int = 0,
        current_hour: int = 12,
        delete_ratio: float = 0.0,
        initial_personality: Optional[str] = None,
        user_confirmed: bool = False,
        confirmation_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        async with self._request_lock:
            return await self._process_request_unlocked(
                user_prompt=user_prompt,
                session_id=session_id,
                project_id=project_id,
                consecutive_errors=consecutive_errors,
                current_hour=current_hour,
                delete_ratio=delete_ratio,
                initial_personality=initial_personality,
                user_confirmed=user_confirmed,
                confirmation_token=confirmation_token,
            )

    async def _process_request_unlocked(
        self,
        user_prompt: str,
        session_id: str,
        project_id: str = "personal",
        consecutive_errors: int = 0,
        current_hour: int = 12,
        delete_ratio: float = 0.0,
        initial_personality: Optional[str] = None,
        user_confirmed: bool = False,
        confirmation_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Asynchronous coordinator running the complete pipeline.
        Parses intent, checks confidence, runs ordered verified tool calls,
        and dynamically triggers matching widgets.
        """
        start_time = time.perf_counter()
        
        # Clear past events for this turn
        self.dispatched_events.clear()

        # Fix #9: restore persisted personality for this session if provided.
        if initial_personality and initial_personality in ("ultron", "zora"):
            if self.personalities.state.active_personality != initial_personality:
                self.personalities.update_state(
                    personality=initial_personality,
                    reason="Restored from session",
                    switch_type="system"
                )

        current_personality = self.personalities.state.active_personality

        # Step 1: DETECT MANUAL SWITCHOVERS
        manual_state = self.personalities.detect_manual_switch(user_prompt)
        if manual_state:
            self._dispatch_event("personality_changed", {
                "active_personality": manual_state.active_personality,
                "reason": manual_state.switch_reason,
                "type": manual_state.switch_type
            })
            current_personality = manual_state.active_personality

        # Step 2: EVALUATE AUTOMATIC TRANSITIONS (Es Score)
        elif current_personality == "ultron":
            should_handoff, stress_score = self.zora_trigger.evaluate_handoff(
                user_prompt=user_prompt,
                consecutive_errors=consecutive_errors,
                current_hour=current_hour,
                delete_ratio=delete_ratio
            )
            
            # Dispatch real-time stress scores
            self._dispatch_event("emotion_score_updated", {
                "stress_score": stress_score,
                "threshold": self.zora_trigger.threshold
            })

            if should_handoff:
                self._dispatch_event("handoff_started", {
                    "source": "ultron",
                    "target": "zora",
                    "reason": f"Stress Score {stress_score:.3f} exceeded threshold."
                })
                
                self.personalities.update_state(
                    personality="zora",
                    reason=f"Auto-handoff: Stress score {stress_score:.3f} reached.",
                    switch_type="automatic"
                )
                
                self._dispatch_event("personality_changed", {
                    "active_personality": "zora",
                    "reason": self.personalities.state.switch_reason,
                    "type": self.personalities.state.switch_type
                })
                
                self._dispatch_event("handoff_completed", {
                    "active_personality": "zora"
                })
                current_personality = "zora"

        # Step 3: ANALYZE INTENT
        intent = self.intent_analyzer.analyze(user_prompt)

        # Step 3b: CODING MODE — pick the right brain/provider for this turn.
        # Coding tasks use the NVIDIA coding model; everything else uses Groq.
        coding_turn = self._should_use_coding_provider(intent, user_prompt)
        provider_for_turn = "nvidia" if coding_turn else "groq"

        # Step 4: COMPUTE CONFIDENCE
        confidence = self.confidence_engine.calculate_confidence(user_prompt, intent)

        # Step 5: DECIDE SPEED TRACK
        speed_track = self.decision_engine.get_speed_track(intent, confidence)

        # Step 6: CACHE DECOUPLED POLICY CHECK
        cache_skip = self.router.cache_policy.should_bypass_cache("", user_prompt)

        # Step 7: RESOLVE STRUCTURED AI ACTION (Fallback)
        structured_action = self._resolve_structured_action(user_prompt)

        # Step 8: HANDLE LOW CONFIDENCE (VAGUE INPUTS)
        if confidence < 0.60:
            clarification_response = (
                "I'm not entirely sure I follow, Sir. Your request lacks context. "
                "Could you clarify what specific file, tool, or goal you want to work on?"
            )
            
            # Save memory
            memory_meta = {
                "personality": current_personality,
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "memory_type": "short_term",
                "confidence": confidence
            }
            self.memory.save_chat_turn(session_id, user_prompt, clarification_response)
            
            end_time = time.perf_counter()
            response_ms = int((end_time - start_time) * 1000)
            
            # Handle Zora automatic lifecycle decrement (update current_personality too,
            # so the session persists the correct value and Zora doesn't get stuck).
            if current_personality == "zora":
                auto_return_state = self.personalities.increment_zora_lifecycle()
                if auto_return_state:
                    self._dispatch_event("personality_changed", {
                        "active_personality": "ultron",
                        "reason": auto_return_state.switch_reason,
                        "type": auto_return_state.switch_type
                    })
            
            return {
                "id": str(uuid.uuid4()),
                "content": clarification_response,
                "intent": intent,
                "confidence": confidence,
                "speed_track": speed_track,
                "cache_skip": cache_skip,
                "response_ms": response_ms,
                "active_personality": current_personality,
                "events": list(self.dispatched_events),
                "metadata": memory_meta,
                "structured_action": {"action": "none"},
                "provider_route": self.router.get_route_metadata(),
            }

        # Step 9: CONTEXT ASSEMBLY & SYSTEM INSTRUCTIONS (With Dynamic 65 Tools schemas!)
        # P0-5: Load last turns from DB (per-session, survives restarts) + merge RAM.
        # The RAM buffer is session-scoped (per-session short-term memory), so two
        # sessions never leak recent turns into each other.
        short_term_context = self.memory.get_session_context(session_id)
        try:
            from backend.app.database.db import get_db_connection
            from backend.app.database.models import get_conversation_history
            with get_db_connection() as _conn:
                db_rows = get_conversation_history(_conn, session_id, limit=8)
            # newest first for merging with RAM; keep chronological order for the prompt
            db_turns = [{"user": r.get("user_message",""), "ai": r.get("ai_response","")} for r in db_rows]
        except Exception as e:
            print(f"[COGNITIVE_ORCHESTRATOR] Warning: DB history load failed: {e}")
            db_turns = []

        # Merge DB history + in-memory short-term (dedupe by exact (user,ai) pair).
        all_turns = db_turns + short_term_context
        seen = set()
        merged = []
        for t in all_turns:
            key = (t.get("user"), t.get("ai"))
            if key not in seen:
                seen.add(key)
                merged.append(t)
        formatted_history = ""
        for turn in merged[-6:]:
            formatted_history += f"User: {turn.get('user','')}\nAI: {turn.get('ai','')}\n"

        active_profile = self.personalities.get_personality(current_personality)
        system_prompt = active_profile.get_system_prompt(formatted_history)

        # Jarvis-style long-term memory injection (episodic + semantic recall).
        # Force a light recall on coding turns so Ultron remembers the project
        # across days; otherwise recall only on explicit memory/past questions.
        memory_context = await self._recall_long_term_memory(
            user_prompt, force=coding_turn, project_id=project_id
        )
        if memory_context:
            system_prompt += memory_context

        # Codex-style: inject project context ONLY on coding turns, so Ultron knows
        # the project it's editing. Skipped on normal chat to save tokens/latency.
        if coding_turn:
            project_ctx = await self._get_project_context_block(project_id)
            if project_ctx:
                system_prompt += project_ctx

            # Inject coding skills (permission-first, multi-file workflow, project rules)
            # from the modular skills/ folder — keeps ultron.md clean & professional.
            try:
                from backend.app.skills.loader import load_coding_skills
                coding_skills = load_coding_skills()
                if coding_skills:
                    system_prompt += "\n\n[CODING_SKILLS]\n" + coding_skills
            except Exception as e:
                print(f"[COGNITIVE_ORCHESTRATOR] Warning: skill loading skipped: {e}")

        # Append tools metadata for LLM-driven autonomous execution.
        # Fix 13: on 'fast' speed-track (simple chat) skip the heavy 65-tool dump to
        # save tokens/latency; include it on medium/heavy/coding turns where tools matter.
        if speed_track == "fast" and not coding_turn:
            system_prompt += (
                "\n\nNote: this is a simple conversational turn. No tool execution is needed."
            )
        else:
            # Phase 3/Point-22: the tool-metadata dump JIT-loads every tool (imports
            # modules + walks schemas). Run it in a worker thread so it can never
            # block the async event loop and freeze the assistant.
            tools_metadata_str = await asyncio.to_thread(self._compile_tools_metadata)
            system_prompt += (
                f"\n\n[AVAILABLE_TOOLS_METADATA]\n{tools_metadata_str}\n\n"
            "First, answer the user briefly and warmly like a human personal assistant "
            "(keep it to 25-40 words, 2 lines max, per your personality). "
            "Then, if you need to execute any tools, output a JSON block "
            "at the very end of your response, wrapped inside `[TOOL_CALLS_START]` and `[TOOL_CALLS_END]`.\n"
            "Example:\n"
            "[TOOL_CALLS_START]\n"
            "[\n"
            "  {\"tool_id\": \"create_folder\", \"args\": {\"folderpath\": \"backend/temp\"}},\n"
            "  {\"tool_id\": \"manage_task\", \"args\": {\"action\": \"create\", \"title\": \"Commit code\"}}\n"
            "]\n"
            "[TOOL_CALLS_END]\n"
            "Tool calls run strictly in the listed order. For coding, inspect before modifying and propose only one modifying step at a time. Do not output tool calls unless relevant."
        )

        # Step 10: ROUTE TO LLM CLIENT
        try:
            ai_response = await self.router.get_completions(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.7,
                provider_preference=provider_for_turn
            )
        except Exception as err:
            print(f"[COGNITIVE_ORCHESTRATOR] Critical: LLM completion failed: {err}")
            ai_response = "I encountered a network timeout while connecting to my core brain, Sir. Let me try resetting the keys."

        # Step 11: PARSE AND EXECUTE LLM TOOL CALLS DYNAMICALLY
        called_tool_ids = []
        tool_results = []
        if "[TOOL_CALLS_START]" in ai_response and "[TOOL_CALLS_END]" in ai_response:
            tool_calls = self._extract_tool_calls(ai_response)
            if tool_calls:
                try:
                    registry = ToolRegistry()
                    tasks_to_run = []
                    task_meta = []  # (tool_id, args) aligned with each coroutine
                    coding_steps_used = 0
                    for call in tool_calls:
                        if not isinstance(call, dict):
                            continue
                        t_id = call.get("tool_id")
                        args = call.get("args", {})
                        if isinstance(args, str):
                            # Some models pass args as an escaped JSON string; parse it.
                            try:
                                args = json.loads(args)
                            except (json.JSONDecodeError, ValueError):
                                args = {}
                        if t_id:
                            # Step B: enforce per-task step limit so a large multi-file
                            # request can never run away / hang.
                            if coding_turn and coding_steps_used >= self.max_coding_steps:
                                tool_results.append({
                                    "tool": t_id,
                                    "args": args,
                                    "success": False,
                                    "error": (f"Step limit reached ({self.max_coding_steps} steps). "
                                              f"Tell the user to continue for the remaining files.")
                                })
                                continue
                            coding_steps_used += 1

                            called_tool_ids.append(t_id)
                            task_meta.append((t_id, args))
                            # Step 3 (permission-first): in coding mode, file writes go
                            # through the safe path (path-guard + backup + atomic) with a
                            # confirmation bound to the exact file+content via a one-time
                            # token. Pass the real user_confirmed flag (previously hardcoded
                            # to False, which made confirmed overwrites never execute).
                            if coding_turn and t_id == "file_write":
                                tasks_to_run.append(
                                    self._coding_safe_write(
                                        args if isinstance(args, dict) else {},
                                        has_confirmed=user_confirmed,
                                        session_id=session_id,
                                        confirmation_token=confirmation_token,
                                    )
                                )
                            else:
                                # Security: only auto-confirm read/write (level 0/1) tools.
                                # Dangerous (level 2/3: terminal, delete, system) need user
                                # confirmation (user_confirmed from a confirm button/API) to run.
                                auto_confirm = False
                                try:
                                    _tool = registry.get_tool(t_id)
                                    auto_confirm = (_tool is not None and _tool.permission_level <= 1)
                                except Exception:
                                    auto_confirm = False
                                tasks_to_run.append(
                                    registry.execute_tool(
                                        tool_id=t_id,
                                        args=args if isinstance(args, dict) else {},
                                        has_confirmed=(auto_confirm or user_confirmed),
                                        confirmation_token=confirmation_token,
                                        session_id=session_id
                                    )
                                )
                    for tid, _targs in task_meta:
                        self._dispatch_log("info", f"Tool call → {tid}")

                    if tasks_to_run:
                        # Execute in declared order. Coding operations stop after the
                        # first failure or pending confirmation so dependent files are
                        # never modified concurrently or after an unverified step.
                        raw_results = []
                        coding_halted = False
                        for index, task in enumerate(tasks_to_run):
                            if coding_halted:
                                close = getattr(task, "close", None)
                                if close:
                                    close()
                                raw_results.append({
                                    "success": False,
                                    "data": {},
                                    "error": "Skipped: previous coding step did not complete successfully.",
                                })
                                continue
                            tid, targs = task_meta[index]
                            filepath = (targs or {}).get("filepath", "")
                            if (
                                coding_turn
                                and tid == "file_write"
                                and self._file_fingerprint(filepath) is not None
                                and not self._has_current_coding_inspection(session_id, filepath)
                            ):
                                close = getattr(task, "close", None)
                                if close:
                                    close()
                                result = {
                                    "success": False,
                                    "data": {},
                                    "error": "Existing file must be read successfully before a coding write.",
                                }
                            else:
                                try:
                                    result = await task
                                except BaseException as exc:
                                    result = exc

                            raw_results.append(result)
                            if (
                                coding_turn
                                and tid == "file_read"
                                and isinstance(result, dict)
                                and result.get("success")
                                and filepath
                            ):
                                self._mark_coding_inspection(session_id, filepath)
                            if (
                                coding_turn
                                and tid == "file_write"
                                and isinstance(result, dict)
                                and result.get("success")
                                and filepath
                            ):
                                self._mark_coding_inspection(session_id, filepath)

                            if coding_turn and (
                                isinstance(result, BaseException)
                                or not isinstance(result, dict)
                                or not result.get("success", False)
                            ):
                                coding_halted = True
                        print(f"[COGNITIVE_ORCHESTRATOR] Sequentially executed tool calls: {called_tool_ids}")

                        # F1: Capture tool outputs so Ultron can answer based on REAL results.
                        for (tid, targs), r in zip(task_meta, raw_results, strict=False):
                            if isinstance(r, BaseException):
                                tool_results.append({
                                    "tool": tid,
                                    "args": targs,
                                    "success": False,
                                    "error": str(r)
                                })
                            elif isinstance(r, dict):
                                # A pending confirmation is NOT an error — surface it
                                # clearly (with its token) so the user can approve.
                                if r.get("status") == "PENDING_CONFIRMATION":
                                    self._dispatch_log(
                                        "info",
                                        f"Awaiting your confirmation for {tid} "
                                        f"(token: {(r.get('confirmation_token') or '')[:8]}…)."
                                    )
                                # Real-time rich log: live 'it's working' feel.
                                elif r.get("success", False):
                                    for level, msg in await self._tool_live_messages(tid, targs, r.get("data", {}) or {}):
                                        self._dispatch_log(level, msg)
                                else:
                                    self._dispatch_log("error", f"Tool {tid} → Error: {(r.get('error') or 'failed')[:80]}")
                                # The unified safe-write path verifies the temporary
                                # candidate before replacing the original.
                                verified = None
                                if coding_turn and tid == "file_write":
                                    verified = (r.get("data") or {}).get("verification")
                                result_item = {
                                    "tool": tid,
                                    "args": targs,
                                    "success": r.get("success", False),
                                    "result": r.get("data", {}),
                                    "error": r.get("error"),
                                }
                                if r.get("status") == "PENDING_CONFIRMATION":
                                    result_item.update({
                                        "status": "PENDING_CONFIRMATION",
                                        "tool_id": r.get("tool_id") or tid,
                                        "confirmation_token": r.get("confirmation_token"),
                                        "message": r.get("message"),
                                        "required_permission_level": r.get("required_permission_level"),
                                        "summary": r.get("summary") or {},
                                        "arguments_hash": r.get("arguments_hash"),
                                        "expires_in_seconds": r.get("expires_in_seconds"),
                                    })
                                if verified is not None:
                                    result_item["verification"] = verified
                                tool_results.append(result_item)
                except Exception as e:
                    print(f"[COGNITIVE_ORCHESTRATOR] Warning: Failed executing tool calls: {e}")

            # Clean raw JSON block from final text response so user gets pristine human output
            ai_response = re.sub(
                r"\[TOOL_CALLS_START\].*?\[TOOL_CALLS_END\]",
                "",
                ai_response,
                flags=re.DOTALL | re.IGNORECASE,
            ).strip()

            # F2: If tools produced real results, feed them back to the LLM so the
            # final answer reflects what actually happened (not a pre-written guess).
            if tool_results:
                try:
                    final_prompt = (
                        f"{user_prompt}\n\n"
                        "[TOOL RESULTS] The following tools were executed. "
                        "Use these REAL results to give an accurate, short, warm answer "
                        "(25-40 words, 2 lines max). If a tool failed, say so honestly. "
                        "For file writes, report the diff-style summary: created/updated, "
                        "file name, and line counts, plus the backup path if present.\\n\\n"
                        + json.dumps(tool_results, indent=2, default=str)[:3000]
                    )
                    final_answer = await self.router.get_completions(
                        system_prompt=system_prompt,
                        user_prompt=final_prompt,
                        temperature=0.5,
                        provider_preference=provider_for_turn
                    )
                    # Only adopt the tool-informed answer if the LLM actually produced text.
                    if final_answer and final_answer.strip():
                        ai_response = final_answer.strip()
                except Exception as e:
                    print(f"[COGNITIVE_ORCHESTRATOR] Warning: Tool-result synthesis failed: {e}")

        # Step 12: DYNAMIC WIDGET ROUTING based on actual called tools
        widget_mappings = {
            "find_files": "file_explorer",
            "create_folder": "file_explorer",
            "rename_folder": "file_explorer",
            "delete_folder": "file_explorer",
            "copy_folder": "file_explorer",
            "move_folder": "file_explorer",
            "list_contents": "file_explorer",
            "compress_folder": "file_explorer",
            "extract_zip": "file_explorer",
            "organize_folder": "file_explorer",
            "manage_task": "todo",
            "manage_calendar": "calendar",
            "manage_reminder": "reminder",
            "security_scan": "security_guardian",
            "daily_briefing": "daily_briefing",
            "optimize_code": "code_optimizer",
            "semantic_code_graph": "semantic_code_graph",
            "git_status": "git",
            "system_metrics": "system",
            "weather_tool": "weather",
            "github_integration": "git"
        }
        
        for t_id in called_tool_ids:
            if t_id in widget_mappings:
                structured_action = {"action": "open_widget", "widget_id": widget_mappings[t_id]}
                break

        # Sync transaction back to short term memory (session-scoped)
        self.memory.save_chat_turn(session_id, user_prompt, ai_response)

        # Jarvis-style long-term persistence remains non-blocking, but is now
        # tracked and cancelled/awaited during application shutdown.
        from backend.app.background_tasks import get_background_task_manager
        get_background_task_manager().create(
            self._persist_turn_to_memory(
                user_prompt,
                ai_response,
                project_id=project_id,
                session_id=session_id,
            ),
            name="memory_persist",
        )

        # Step 13: ZORA OVERLAY LIFECYCLE DECREMENT
        if current_personality == "zora":
            auto_return_state = self.personalities.increment_zora_lifecycle()
            if auto_return_state:
                self._dispatch_event("personality_changed", {
                    "active_personality": "ultron",
                    "reason": auto_return_state.switch_reason,
                    "type": auto_return_state.switch_type
                })

        end_time = time.perf_counter()
        response_ms = int((end_time - start_time) * 1000)

        # Surface any pending confirmation so clients can capture its one-time
        # token and send it back with has_confirmed=true (bound to file+content).
        pending_confirmation = None
        for tr in tool_results:
            if isinstance(tr, dict) and tr.get("status") == "PENDING_CONFIRMATION":
                pending_confirmation = {
                    "tool_id": tr.get("tool_id"),
                    "confirmation_token": tr.get("confirmation_token"),
                    "message": tr.get("message"),
                    "required_permission_level": tr.get("required_permission_level"),
                    "summary": tr.get("summary") or {},
                    "arguments_hash": tr.get("arguments_hash"),
                    "expires_in_seconds": tr.get("expires_in_seconds"),
                }
                break

        # Compile standard memory metadata parameters
        memory_meta = {
            "personality": current_personality,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "memory_type": "short_term",
            "confidence": confidence
        }

        return {
            "id": str(uuid.uuid4()),
            "content": ai_response,
            "intent": intent,
            "confidence": confidence,
            "speed_track": speed_track,
            "cache_skip": cache_skip,
            "response_ms": response_ms,
            "active_personality": current_personality,
            # P0-6: the personality to persist to the session — after any Zora
            # auto-return this is 'ultron' (so Zora doesn't get stuck across days),
            # while the current response still reports who answered (current_personality).
            "persisted_personality": self.personalities.state.active_personality,
            "events": list(self.dispatched_events),
            "metadata": memory_meta,
            "structured_action": structured_action,
            "coding": coding_turn,
            "pending_confirmation": pending_confirmation,
            "provider_route": self.router.get_route_metadata(),
        }

    async def close(self) -> None:
        """Saves persistent caches and closes active async connections cleanly."""
        self.router.cache.save_to_disk()
        await self.router.close()

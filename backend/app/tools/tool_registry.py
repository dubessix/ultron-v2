"""
Ultron Core Tool Execution Registry (Deferred JIT optimized)
Registers tools using a lightweight dynamic JIT importer to keep memory <20MB on boot.
Implements schema validations, security confirmations, async timeouts, and SQLite audits.
"""

import hashlib
import time
import uuid
import json
import asyncio
import sqlite3
import importlib
from contextlib import nullcontext
from typing import Dict, Any, List, Optional
from pydantic import ValidationError

from backend.app.database.db import (
    DatabaseMaintenanceError,
    get_db_connection,
    maintenance_coordinator,
)
from backend.app.tools.tool_base import BaseTool, ToolResult
from backend.app.security.confirmation_gate import ConfirmationGate
from backend.app.security.pending_actions import get_pending_action_registry


_SENSITIVE_ARGUMENT_MARKERS = ("content", "password", "token", "secret", "authorization", "api_key")


def _redact_audit_arguments(value: Any, key: str = "") -> Any:
    """Bound audit size and replace secret/file-content values with metadata."""
    lowered = key.lower()
    if any(marker in lowered for marker in _SENSITIVE_ARGUMENT_MARKERS):
        text = str(value or "")
        return {
            "redacted": True,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "bytes": len(text.encode("utf-8")),
        }
    if isinstance(value, dict):
        return {str(k): _redact_audit_arguments(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_audit_arguments(item, key) for item in value[:100]]
    if isinstance(value, str) and len(value) > 500:
        return value[:500] + "…[truncated]"
    return value


class ToolRegistry:
    def __init__(self, gate: Optional[ConfirmationGate] = None) -> None:
        self.gate = gate or ConfirmationGate()
        self._tools: Dict[str, BaseTool] = {}
        self._initialize_audit_table()
        self._register_default_tools_lazy()

    def _initialize_audit_table(self) -> None:
        """Initializes self-contained tool_audit_logs table on boot."""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS tool_audit_logs (
                        id TEXT PRIMARY KEY,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        tool_name TEXT NOT NULL,
                        arguments TEXT NOT NULL,
                        duration_ms INTEGER NOT NULL,
                        success BOOLEAN NOT NULL,
                        session_id TEXT,
                        permission_level INTEGER NOT NULL,
                        error TEXT
                    );
                """)
                conn.commit()
        except (DatabaseMaintenanceError, OSError) as e:
            print(f"[TOOL_REGISTRY] Audit table unavailable during maintenance: {e}")

    def _log_audit_transaction(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        duration_ms: int,
        success: bool,
        session_id: Optional[str],
        permission_level: int,
        error: Optional[str]
    ) -> None:
        """Logs tool transactions cleanly into persistent SQLite database."""
        log_id = str(uuid.uuid4())
        args_str = json.dumps(_redact_audit_arguments(arguments), default=str)
        try:
            with get_db_connection() as conn:
                try:
                    cursor = conn.cursor()
                    # A confirmed database restore can replace the file after this
                    # registry instance initialized. Re-create the audit table in
                    # the restored DB before recording the restore result.
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS tool_audit_logs (
                            id TEXT PRIMARY KEY,
                            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                            tool_name TEXT NOT NULL,
                            arguments TEXT NOT NULL,
                            duration_ms INTEGER NOT NULL,
                            success BOOLEAN NOT NULL,
                            session_id TEXT,
                            permission_level INTEGER NOT NULL,
                            error TEXT
                        );
                    """)
                    cursor.execute(
                        """
                        INSERT INTO tool_audit_logs (
                            id, tool_name, arguments, duration_ms, success, session_id, permission_level, error
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (log_id, tool_name, args_str, duration_ms, success, session_id, permission_level, error)
                    )
                    conn.commit()
                except sqlite3.Error as e:
                    print(f"[TOOL_REGISTRY] Warning: Failed to write to audit logger: {e}")
        except (DatabaseMaintenanceError, OSError) as e:
            # A restore intentionally pauses all DB writes. Audit logging must not
            # turn that expected maintenance state into a false tool success/crash.
            print(f"[TOOL_REGISTRY] Audit deferred during database unavailability: {e}")

    def _register_default_tools_lazy(self) -> None:
        """
        DEFERRED JIT IMPORTS (Requirement: Zero RAM on startup)
        Register tool mappings as lightweight tuple configurations.
        Modules are imported ONLY when the specific tool is executed or queried.
        """
        self._lazy_tools = {
            "file_read": ("backend.app.tools.filesystem_tools", "FileReadTool"),
            "file_write": ("backend.app.tools.filesystem_tools", "FileWriteTool"),
            "find_files": ("backend.app.tools.filesystem_tools", "FindFilesTool"),
            "terminal_run": ("backend.app.tools.system_tools", "TerminalRunTool"),
            "open_calculator": ("backend.app.tools.system_tools", "CalculatorTool"),
            "open_chrome": ("backend.app.tools.system_tools", "ChromeLauncherTool"),
            "open_vscode": ("backend.app.tools.system_tools", "VSCodeLauncherTool"),
            "weather_tool": ("backend.app.tools.weather_tool", "WeatherTool"),
            "tavily_research": ("backend.app.tools.research_tool", "TavilyResearchTool"),
            "git_status": ("backend.app.tools.git_tool", "GitStatusTool"),
            "git_clone": ("backend.app.tools.git_tool", "GitCloneTool"),
            "system_metrics": ("backend.app.tools.system_metrics_tool", "SystemMetricsTool"),
            "create_folder": ("backend.app.tools.folder_tools", "CreateFolderTool"),
            "rename_folder": ("backend.app.tools.folder_tools", "RenameFolderTool"),
            "delete_folder": ("backend.app.tools.folder_tools", "DeleteFolderTool"),
            "copy_folder": ("backend.app.tools.folder_tools", "CopyFolderTool"),
            "move_folder": ("backend.app.tools.folder_tools", "MoveFolderTool"),
            "list_contents": ("backend.app.tools.folder_tools", "ListContentsTool"),
            "compress_folder": ("backend.app.tools.folder_tools", "CompressFolderTool"),
            "extract_zip": ("backend.app.tools.folder_tools", "ExtractZipTool"),
            "organize_folder": ("backend.app.tools.folder_tools", "OrganizeFolderTool"),
            "open_url": ("backend.app.tools.browser_tools", "OpenUrlTool"),
            "open_new_tab": ("backend.app.tools.browser_tools", "OpenNewTabTool"),
            "close_tab": ("backend.app.tools.browser_tools", "CloseCurrentTabTool"),
            "refresh_page": ("backend.app.tools.browser_tools", "RefreshPageTool"),
            "browser_back": ("backend.app.tools.browser_tools", "BackTool"),
            "browser_forward": ("backend.app.tools.browser_tools", "ForwardTool"),
            "close_browser": ("backend.app.tools.browser_tools", "CloseBrowserTool"),
            "download_file": ("backend.app.tools.browser_tools", "DownloadFileTool"),
            "read_current_page": ("backend.app.tools.browser_tools", "ReadPageTool"),
            "google_search": ("backend.app.tools.web_search_tools", "GoogleSearchTool"),
            "github_search": ("backend.app.tools.web_search_tools", "GitHubSearchTool"),
            "stackoverflow_search": ("backend.app.tools.web_search_tools", "StackOverflowSearchTool"),
            "reddit_search": ("backend.app.tools.web_search_tools", "RedditSearchTool"),
            "image_search": ("backend.app.tools.web_search_tools", "ImageSearchTool"),
            "news_search": ("backend.app.tools.web_search_tools", "NewsSearchTool"),
            "video_search": ("backend.app.tools.web_search_tools", "VideoSearchTool"),
            "play_music": ("backend.app.tools.music_tools", "PlayMusicTool"),
            "pause_music": ("backend.app.tools.music_tools", "PauseMusicTool"),
            "resume_music": ("backend.app.tools.music_tools", "ResumeMusicTool"),
            "next_track": ("backend.app.tools.music_tools", "NextTrackTool"),
            "previous_track": ("backend.app.tools.music_tools", "PreviousTrackTool"),
            "stop_music": ("backend.app.tools.music_tools", "StopMusicTool"),
            "set_volume": ("backend.app.tools.music_tools", "SetVolumeTool"),
            "current_track": ("backend.app.tools.music_tools", "CurrentTrackTool"),
            "open_spotify": ("backend.app.tools.spotify_tools", "OpenSpotifyTool"),
            "spotify_play": ("backend.app.tools.spotify_tools", "SpotifyPlaySongTool"),
            "spotify_search_artist": ("backend.app.tools.spotify_tools", "SpotifySearchArtistTool"),
            "spotify_playlist": ("backend.app.tools.spotify_tools", "SpotifyPlayPlaylistTool"),
            "spotify_pause": ("backend.app.tools.spotify_tools", "SpotifyPauseTool"),
            "spotify_resume": ("backend.app.tools.spotify_tools", "SpotifyResumeTool"),
            "spotify_next": ("backend.app.tools.spotify_tools", "SpotifyNextTool"),
            "spotify_prev": ("backend.app.tools.spotify_tools", "SpotifyPreviousTool"),
            "spotify_set_volume": ("backend.app.tools.spotify_tools", "SpotifyVolumeTool"),
            "spotify_current_track": ("backend.app.tools.spotify_tools", "SpotifyCurrentTrackTool"),
            "optimize_code": ("backend.app.tools.code_optimizer_tool", "CodeOptimizerTool"),
            "semantic_code_graph": ("backend.app.tools.semantic_graph_tool", "SemanticGraphTool"),
            "manage_reminder": ("backend.app.tools.reminder_tool", "ReminderTool"),
            "manage_task": ("backend.app.tools.task_tool", "TaskTool"),
            "manage_calendar": ("backend.app.tools.calendar_tool", "CalendarTool"),
            "security_scan": ("backend.app.tools.security_guardian_tool", "SecurityGuardianTool"),
            "daily_briefing": ("backend.app.tools.daily_briefing_tool", "DailyBriefingTool"),
            "manage_memory": ("backend.app.tools.memory_tool", "MemoryTool"),
            "search_inside_documents": ("backend.app.tools.filesystem_search_tool", "SearchDocumentsTool"),
            "convert_file_format": ("backend.app.tools.filesystem_search_tool", "ConvertFileFormatTool"),
            "world_monitor": ("backend.app.tools.world_monitor_tool", "WorldMonitorTool"),
            "github_integration": ("backend.app.tools.github_integration_tool", "GitHubIntegrationTool"),
            "database_restore": ("backend.app.tools.database_tools", "DatabaseRestoreTool"),
            "universal_search": ("backend.app.tools.universal_search_tool", "UniversalSearchTool"),
        }

    def register(self, tool: BaseTool) -> None:
        """Register a new custom tool dynamically (OCP compliant)."""
        self._tools[tool.id] = tool

    def get_tool(self, tool_id: str) -> Optional[BaseTool]:
        """Resolves and JIT-loads the requested tool on demand, keeping idle RAM footprint extremely low."""
        if tool_id in self._tools:
            return self._tools[tool_id]
            
        if tool_id in self._lazy_tools:
            mod_path, class_name = self._lazy_tools[tool_id]
            try:
                mod = importlib.import_module(mod_path)
                tool_class = getattr(mod, class_name)
                tool_instance = tool_class()
                self._tools[tool_id] = tool_instance
                return tool_instance
            except Exception as e:
                print(f"[TOOL_REGISTRY] JIT Load failed for {tool_id}: {e}")
                return None
        return None

    def get_all_tools(self) -> List[BaseTool]:
        """Returns a list of all tools, loading any lazy tools on demand."""
        # JIT load all missing tools
        for tool_id in self._lazy_tools:
            if tool_id not in self._tools:
                self.get_tool(tool_id)
        return list(self._tools.values())

    def get_registered_ids(self) -> List[str]:
        """Returns a combined list of all registered active and lazy tool IDs."""
        ids = list(self._tools.keys())
        for lazy_id in self._lazy_tools:
            if lazy_id not in ids:
                ids.append(lazy_id)
        return ids

    async def execute_tool(
        self,
        tool_id: str,
        args: Dict[str, Any],
        has_confirmed: bool = False,
        confirmation_token: Optional[str] = None,
        session_id: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: int = 0,
        _confirmation_prevalidated: bool = False,
    ) -> Dict[str, Any]:
        """
        Main execution router.
        JIT-loads the target tool, validates, audits, and executes it.
        """
        start_time = time.perf_counter()
        tool = self.get_tool(tool_id)
        
        if not tool:
            err_msg = f"Tool '{tool_id}' not registered in the system."
            return {
                "success": False,
                "data": {},
                "error": err_msg,
                "metadata": {"execution_time_ms": 0, "tool_name": tool_id}
            }

        # 1. Validate inputs against Pydantic schema model
        permission_level = tool.permission_level
        try:
            validated_args = tool.args_model(**args)
            args_payload = validated_args.model_dump()
            permission_level = tool.permission_for_arguments(args_payload)
        except ValidationError as val_err:
            print(f"[TOOL_REGISTRY] Validation failed for tool '{tool_id}': {val_err}")
            err_payload = {
                "success": False,
                "data": {},
                "error": "Input validation schema match failed.",
                "metadata": {"execution_time_ms": 0, "tool_name": tool.name}
            }
            # Log failure to audit table
            self._log_audit_transaction(
                tool_name=tool.name,
                arguments=args,
                duration_ms=0,
                success=False,
                session_id=session_id,
                permission_level=permission_level,
                error="ValidationError: Input schema mismatch"
            )
            return err_payload

        # Reject unsafe paths before creating a confirmation prompt. The user
        # should never be asked to approve an action the path policy will deny.
        from backend.app.security.path_guard import validate_tool_paths
        path_check = validate_tool_paths(tool_id, args_payload)
        if not path_check["safe"]:
            return {
                "success": False,
                "data": {},
                "error": (
                    f"Path argument '{path_check['field']}' blocked "
                    f"({path_check['reason']}): {path_check['path']}"
                ),
                "metadata": {"execution_time_ms": 0, "tool_name": tool.name},
            }

        # 2. Exact one-time confirmation for every Level 2/3 action. A raw
        # has_confirmed=True boolean is never authorization by itself.
        requires_confirmation = self.gate.manager.requires_manual_confirmation(
            permission_level
        )
        if requires_confirmation and not _confirmation_prevalidated:
            pending = get_pending_action_registry()
            if has_confirmed and confirmation_token:
                validation = pending.validate(
                    confirmation_token,
                    tool_id,
                    session_id,
                    args_payload,
                )
                if not validation["valid"]:
                    created = pending.create(tool_id, session_id, args_payload)
                    self._log_audit_transaction(
                        tool.name, args_payload, 0, False, session_id,
                        permission_level,
                        f"CONFIRMATION_REJECTED:{validation['reason']}",
                    )
                    return {
                        "success": False,
                        "status": "PENDING_CONFIRMATION",
                        "tool_id": tool_id,
                        "message": (
                            f"Confirmation rejected ({validation['reason']}). "
                            f"Approve the newly-issued exact action for '{tool_id}'."
                        ),
                        "required_permission_level": permission_level,
                        **created,
                    }
            else:
                created = pending.create(tool_id, session_id, args_payload)
                self._log_audit_transaction(
                    tool.name, args_payload, 0, False, session_id,
                    permission_level, "PENDING_CONFIRMATION",
                )
                return {
                    "success": False,
                    "status": "PENDING_CONFIRMATION",
                    "tool_id": tool_id,
                    "message": f"Tool '{tool_id}' requires exact one-time confirmation.",
                    "required_permission_level": permission_level,
                    **created,
                }

        # 3. Async execution under timeout and retry boundaries. Write/system
        # tools participate in the same maintenance gate as DB connections: a
        # restore waits for an in-flight action, and new actions fail clearly.
        raw_result = None
        execution_error = None
        operation_guard = (
            maintenance_coordinator.database_access()
            if permission_level >= 1 and tool_id != "database_restore"
            else nullcontext()
        )
        try:
            with operation_guard:
                for attempt in range(max_retries + 1):
                    try:
                        raw_result = await asyncio.wait_for(
                            tool.execute(**args_payload),
                            timeout=timeout
                        )
                        execution_error = None
                        break
                    except asyncio.TimeoutError:
                        execution_error = f"TimeoutError: Execution exceeded limit of {timeout}s."
                        print(f"[TOOL_REGISTRY] Timeout on '{tool_id}' (Attempt {attempt + 1}/{max_retries + 1}).")
                    except Exception as e:
                        execution_error = f"ExecutionCrash: {e}"
                        print(f"[TOOL_REGISTRY] Crash on '{tool_id}' (Attempt {attempt + 1}/{max_retries + 1}).")

                    if attempt < max_retries:
                        await asyncio.sleep(0.5)
        except DatabaseMaintenanceError as e:
            execution_error = f"DatabaseMaintenance: {e}"

        end_time = time.perf_counter()
        duration_ms = int((end_time - start_time) * 1000)

        # 4. Compile Standardized ToolResult
        if execution_error:
            result_model = ToolResult(
                success=False,
                data={},
                error=execution_error,
                metadata={"execution_time_ms": duration_ms, "tool_name": tool.name}
            )
        else:
            result_model = ToolResult(
                success=raw_result.get("success", False),
                data=raw_result.get("data", {}),
                error=raw_result.get("error"),
                metadata={"execution_time_ms": duration_ms, "tool_name": tool.name}
            )

        # 5. Log transaction cleanly to SQLite audit table
        self._log_audit_transaction(
            tool_name=tool.name,
            arguments=args_payload,
            duration_ms=duration_ms,
            success=result_model.success,
            session_id=session_id,
            permission_level=permission_level,
            error=result_model.error
        )

        return result_model.model_dump()

    async def execute_pending_action(
        self,
        confirmation_token: str,
        session_id: Optional[str],
        *,
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """Claim and execute the exact stored action without another LLM call."""
        claimed = get_pending_action_registry().claim(confirmation_token, session_id)
        if not claimed["valid"]:
            return {
                "success": False,
                "data": {},
                "error": f"Confirmation rejected: {claimed['reason']}",
                "status": "CONFIRMATION_REJECTED",
            }
        action = claimed["action"]
        return await self.execute_tool(
            tool_id=action["tool_id"],
            args=action["arguments"],
            session_id=session_id,
            timeout=timeout,
            max_retries=0,
            _confirmation_prevalidated=True,
        )

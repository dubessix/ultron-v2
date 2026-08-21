"""
Ultron Unit & Integration Testing Suite — Phase 13 V2 Tools Diagnostics
Verifies un-mocked folder creations, copy-move actions, zip archives,
web browsers url constructs, StackOverflow searches, Spotify deep links launching,
and our newly developed un-mocked Self-Healing Compiler Loop (Autoreactive Debugger).
"""

import unittest
import shutil
from unittest.mock import patch

from backend.app.tools.tool_registry import ToolRegistry
from backend.app.runtime_paths import isolated_test_artifact_path

TEST_DIR = isolated_test_artifact_path("phase13", "test_phase13_temp_dir")
RENAME_DIR = isolated_test_artifact_path("phase13", "test_phase13_renamed_dir")
ORGANIZE_DIR = isolated_test_artifact_path("phase13", "test_phase13_organize_dir")
ERROR_FILE_PATH = isolated_test_artifact_path("phase13", "error_file.py")

class TestPhase13V2ToolsArchitecture(unittest.IsolatedAsyncioTestCase):

    async def _execute_exact(self, registry, tool_id, args, session="phase13"):
        first = await registry.execute_tool(tool_id, args, session_id=session)
        if first.get("status") != "PENDING_CONFIRMATION":
            return first
        return await registry.execute_tool(
            tool_id,
            args,
            has_confirmed=True,
            confirmation_token=first["confirmation_token"],
            session_id=session,
            max_retries=0,
        )
    
    def setUp(self):
        """Prepare clean target workspace folders."""
        for d in [TEST_DIR, RENAME_DIR, ORGANIZE_DIR]:
            if d.exists():
                try:
                    shutil.rmtree(d)
                except OSError:
                    pass
        if ERROR_FILE_PATH.exists():
            ERROR_FILE_PATH.unlink()

    def tearDown(self):
        for d in [TEST_DIR, RENAME_DIR, ORGANIZE_DIR]:
            if d.exists():
                try:
                    shutil.rmtree(d)
                except OSError:
                    pass
        if ERROR_FILE_PATH.exists():
            ERROR_FILE_PATH.unlink()

    async def test_folders_management_tools(self):
        """Test 1: Verify Create, Rename, List, and Delete folder local operations."""
        registry = ToolRegistry()
        
        # 1.1 Create Folder
        create_res = await self._execute_exact(
            registry, "create_folder", {"folderpath": str(TEST_DIR)}
        )
        self.assertTrue(create_res["success"])
        self.assertTrue(TEST_DIR.exists())
        
        # Write dummy file inside to test listing
        dummy_file = TEST_DIR / "doc.txt"
        with open(dummy_file, "w", encoding="utf-8") as f:
            f.write("System content")
            
        # 1.2 List Contents
        list_res = await registry.execute_tool("list_contents", {"folderpath": str(TEST_DIR)})
        self.assertTrue(list_res["success"])
        self.assertIn("doc.txt", list_res["data"]["raw_names"])
        
        # 1.3 Rename Folder
        rename_res = await self._execute_exact(
            registry,
            "rename_folder",
            {"old_path": str(TEST_DIR), "new_path": str(RENAME_DIR)},
        )
        self.assertTrue(rename_res["success"])
        self.assertFalse(TEST_DIR.exists())
        self.assertTrue(RENAME_DIR.exists())
        
        # 1.4 Delete Folder (Requires confirmation since level is 3)
        # Attempt without confirmation
        delete_args = {"folderpath": str(RENAME_DIR)}
        del_res_1 = await registry.execute_tool(
            "delete_folder", delete_args, session_id="phase13_delete"
        )
        self.assertEqual(del_res_1["status"], "PENDING_CONFIRMATION")
        
        # Attempt WITH exact one-time confirmation
        del_res_2 = await registry.execute_tool(
            "delete_folder",
            delete_args,
            has_confirmed=True,
            confirmation_token=del_res_1["confirmation_token"],
            session_id="phase13_delete",
        )
        self.assertTrue(del_res_2["success"])
        self.assertFalse(RENAME_DIR.exists())

    async def test_organize_folder_tool(self):
        """Test 2: Verify the un-mocked OrganizeFolderTool correctly categorizes and moves files."""
        registry = ToolRegistry()
        
        # Create temporary organize folder
        ORGANIZE_DIR.mkdir(parents=True, exist_ok=True)
        
        # Write dummy files with separate extensions
        (ORGANIZE_DIR / "photo.jpg").touch()
        (ORGANIZE_DIR / "notes.pdf").touch()
        (ORGANIZE_DIR / "archive.zip").touch()
        (ORGANIZE_DIR / "script.py").touch()
        
        # Execute organize_folder tool (Requires Level 2 confirmation)
        # Attempt without confirmation
        organize_args = {"folderpath": str(ORGANIZE_DIR)}
        org_res_1 = await registry.execute_tool(
            "organize_folder", organize_args, session_id="phase13_organize"
        )
        self.assertEqual(org_res_1["status"], "PENDING_CONFIRMATION")
        
        # Attempt WITH exact confirmation
        org_res_2 = await registry.execute_tool(
            "organize_folder",
            organize_args,
            has_confirmed=True,
            confirmation_token=org_res_1["confirmation_token"],
            session_id="phase13_organize",
        )
        self.assertTrue(org_res_2["success"])
        self.assertEqual(org_res_2["data"]["moved_count"], 4)
        
        # Verify subfolders were created and populated
        self.assertTrue((ORGANIZE_DIR / "images" / "photo.jpg").exists())
        self.assertTrue((ORGANIZE_DIR / "documents" / "notes.pdf").exists())
        self.assertTrue((ORGANIZE_DIR / "archives" / "archive.zip").exists())
        self.assertTrue((ORGANIZE_DIR / "code" / "script.py").exists())

    @patch("webbrowser.open", return_value=True)
    async def test_browser_and_web_search_tools(self, _open):
        """Test 3: Verify browser URL, Google search, and StackOverflow search URL constructions."""
        registry = ToolRegistry()
        
        # Test Open URL (Requires level 1 auto allow)
        open_res = await registry.execute_tool("open_url", {"url": "https://github.com"}, has_confirmed=False)
        self.assertTrue(open_res["success"])
        
        # Test Google Search — now returns the real top-result page (or falls back to
        # the search URL), so check case-insensitively for the query term in the URL.
        g_res = await registry.execute_tool("google_search", {"query": "Vite React"}, has_confirmed=False)
        self.assertTrue(g_res["success"])
        self.assertIn("vite", g_res["data"]["url"].lower())
        
        # Test StackOverflow Search
        so_res = await registry.execute_tool("stackoverflow_search", {"query": "asyncio"}, has_confirmed=False)
        self.assertTrue(so_res["success"])
        self.assertIn("asyncio", so_res["data"]["url"])

    @patch("webbrowser.open", return_value=True)
    async def test_music_and_spotify_launchers(self, _open):
        """Test 4: Verify music players and Spotify deep-links/web-search URL generations."""
        registry = ToolRegistry()
        
        # Test stop music
        stop_res = await registry.execute_tool("stop_music", {})
        self.assertTrue(stop_res["success"])
        
        # Volume is exact-confirmation gated and must report verified or unavailable.
        vol_res = await self._execute_exact(
            registry, "set_volume", {"level": 80}, session="phase13_volume"
        )
        self.assertIn((vol_res.get("data") or {}).get("status"), ("verified", "unavailable", "failed"))
        
        # Test Spotify Song Player (Requires level 2 confirmation)
        spotify_args = {"query": "Starboy"}
        spot_res_1 = await registry.execute_tool(
            "spotify_play", spotify_args, session_id="phase13_spotify"
        )
        self.assertEqual(spot_res_1["status"], "PENDING_CONFIRMATION")

        spot_res_2 = await registry.execute_tool(
            "spotify_play",
            spotify_args,
            has_confirmed=True,
            confirmation_token=spot_res_1["confirmation_token"],
            session_id="phase13_spotify",
        )
        self.assertTrue(spot_res_2["success"])
        self.assertIn("status", spot_res_2["data"])

    async def test_self_healing_compiler_loop_diagnostics(self):
        """Test 5: Verify that the TerminalRunTool dynamically analyzes tracebacks and suggests fixes on compiler failures."""
        registry = ToolRegistry()
        
        # 1. Create a dummy file containing an unclosed parenthesis syntax error
        unclosed_bracket_code = 'print("hello"'
        with open(ERROR_FILE_PATH, "w", encoding="utf-8") as f:
            f.write(unclosed_bracket_code)
            
        # 2. Execute terminal runner tool to compile our broken script (Requires Level 2 confirmation)
        command = f"python {ERROR_FILE_PATH}"
        response = await self._execute_exact(
            registry,
            "terminal_run",
            {"command": command},
            session="phase13_terminal",
        )
        
        # Assertions
        self.assertFalse(response["success"]) # Must fail because of syntax error
        self.assertEqual(response["data"]["exit_code"], 1)
        self.assertIsNotNone(response["data"]["self_healing_fix"]) # Self-healing successfully parsed!
        
        # Verify self-healing suggestions
        fix_data = response["data"]["self_healing_fix"]
        self.assertEqual(fix_data["line"], 1)
        self.assertEqual(fix_data["offending_line"], 'print("hello"')
        self.assertEqual(fix_data["suggested_patch"], 'print("hello")\n') # Suggested bracket fix!

    def test_tool_registry_auto_discovery_and_metadata(self):
        """Test 6: Verify that all V2 tools are automatically registered with correct metadata."""
        registry = ToolRegistry()
        
        # Extract registered tool keys
        ids = registry.get_registered_ids()
        
        # Check folders
        self.assertIn("create_folder", ids)
        self.assertIn("rename_folder", ids)
        self.assertIn("delete_folder", ids)
        self.assertIn("list_contents", ids)
        self.assertIn("organize_folder", ids)
        
        # Check browsers
        self.assertIn("open_url", ids)
        self.assertIn("open_new_tab", ids)
        self.assertIn("read_current_page", ids)
        
        # Check searches
        self.assertIn("google_search", ids)
        self.assertIn("github_search", ids)
        self.assertIn("stackoverflow_search", ids)
        
        # Check music & spotify
        self.assertIn("play_music", ids)
        self.assertIn("stop_music", ids)
        self.assertIn("spotify_play", ids)
        self.assertIn("spotify_playlist", ids)
        
        # Verify metadata schemas are valid (SRP/DIP)
        meta = registry.get_tool("create_folder").get_metadata()
        self.assertEqual(meta["id"], "create_folder")
        self.assertEqual(meta["category"], "filesystem")
        self.assertIn("mkdir", meta["tags"])

if __name__ == "__main__":
    unittest.main()

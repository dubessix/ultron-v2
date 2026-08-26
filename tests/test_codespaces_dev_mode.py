"""Regression checks for direct GitHub Codespaces browser mode."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_codespaces_uses_direct_forwarded_browser_not_novnc():
    config = json.loads((ROOT / ".devcontainer" / "devcontainer.json").read_text(encoding="utf-8"))
    assert config["build"]["dockerfile"] == "Dockerfile"
    assert "features" not in config or "ghcr.io/devcontainers/features/desktop-lite:1" not in config.get("features", {})
    assert config["forwardPorts"] == [5173]
    assert config["portsAttributes"]["5173"]["onAutoForward"] == "openBrowserOnce"
    assert config["portsAttributes"]["5173"]["visibility"] == "private"
    assert config["portsAttributes"]["8000"]["onAutoForward"] == "ignore"
    assert config["containerEnv"]["ULTRON_CODESPACES_WEB"] == "1"
    assert "codespaces_prepare.sh" in config["postCreateCommand"]
    assert "postStartCommand" not in config

    prepare = (ROOT / ".devcontainer" / "codespaces_prepare.sh").read_text(encoding="utf-8")
    assert "start_codespaces_web.sh" in prepare
    assert "No desktop, VNC, or noVNC service" in prepare
    assert not (ROOT / ".devcontainer" / "codespaces_desktop.sh").exists()
    assert not (ROOT / ".devcontainer" / "codespaces_launch_setup.sh").exists()


def test_codespaces_web_launcher_owns_both_services_and_uses_relative_proxy_mode():
    launcher = (ROOT / "start_codespaces_web.sh").read_text(encoding="utf-8")
    vite = (ROOT / "frontend" / "vite.config.js").read_text(encoding="utf-8")
    api = (ROOT / "frontend" / "src" / "api.js").read_text(encoding="utf-8")

    for required in (
        "ULTRON_CODESPACES_WEB=1",
        "VITE_API_URL=.",
        "uvicorn backend.app.main:app --host 127.0.0.1 --port 8000",
        "npm run dev -- --host 0.0.0.0 --port 5173",
        "wait -n",
        "cleanup()",
    ):
        assert required in launcher
    assert "codespacesWebMode" in vite
    assert "'/api'" in vite
    assert "'/ws'" in vite
    assert "0.0.0.0" in vite
    assert "websocketBase" in api
    assert "configuredApiBase === undefined" in api


def test_codespaces_image_has_only_terminal_web_prerequisites_without_keys():
    dockerfile = (ROOT / ".devcontainer" / "Dockerfile").read_text(encoding="utf-8")
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / ".devcontainer").glob("*"))
        if path.is_file()
    )
    assert "mcr.microsoft.com/devcontainers/universal:5.1-linux" in dockerfile
    assert "python3-venv" in dockerfile
    assert "google-chrome-stable" not in dockerfile
    assert "desktop-lite" not in combined
    for secret_name in (
        "GROQ_API_KEY_1=",
        "GEMINI_API_KEY_1=",
        "NVIDIA_API_KEY_1=",
        "TAVILY_API_KEY=",
        "GITHUB_TOKEN_1=",
        "GH_TOKEN=",
    ):
        assert secret_name not in combined


def test_generated_source_mode_shortcut_directory_is_ignored():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "app_shortcuts/" in ignore

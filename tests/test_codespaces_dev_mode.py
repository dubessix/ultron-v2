"""Regression checks for the no-key GitHub Codespaces Ubuntu desktop demo."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_codespaces_uses_private_lightweight_desktop_and_real_setup_wrapper():
    config = json.loads((ROOT / ".devcontainer" / "devcontainer.json").read_text(encoding="utf-8"))
    assert config["build"]["dockerfile"] == "Dockerfile"
    assert "ghcr.io/devcontainers/features/desktop-lite:1" in config["features"]
    assert config["forwardPorts"] == [6080]
    assert config["portsAttributes"]["6080"]["onAutoForward"] == "openBrowserOnce"
    assert config["portsAttributes"]["5173"]["onAutoForward"] == "ignore"
    assert config["portsAttributes"]["8000"]["onAutoForward"] == "ignore"
    assert "codespaces_prepare.sh" in config["postCreateCommand"]
    assert "codespaces_desktop.sh" in config["postStartCommand"]

    desktop = (ROOT / ".devcontainer" / "codespaces_desktop.sh").read_text(encoding="utf-8")
    launch = (ROOT / ".devcontainer" / "codespaces_launch_setup.sh").read_text(encoding="utf-8")
    assert "xdpyinfo" in desktop
    assert "pcmanfm --desktop" in desktop
    assert "codespaces_launch_setup.sh" in desktop
    assert 'SETUP_ULTRON_UBUNTU.sh' in launch
    assert "backend.app.installer" not in launch  # The real platform wrapper owns startup.


def test_codespaces_image_has_signed_browser_and_gui_prerequisites_without_keys():
    dockerfile = (ROOT / ".devcontainer" / "Dockerfile").read_text(encoding="utf-8")
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / ".devcontainer").glob("*"))
        if path.is_file()
    )
    assert "mcr.microsoft.com/devcontainers/universal:5.1-linux" in dockerfile
    assert "python3-tk" in dockerfile
    assert "python3-venv" in dockerfile
    assert "pcmanfm" in dockerfile
    assert "google-chrome-stable" in dockerfile
    assert "signed-by=/usr/share/keyrings/google-chrome.gpg" in dockerfile
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

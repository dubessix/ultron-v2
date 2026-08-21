"""Regression checks for the manual, credential-free Windows/Ubuntu cloud gate."""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent


def test_cloud_workflow_is_manual_read_only_and_cross_platform():
    workflow = ROOT / ".github" / "workflows" / "ultron-cloud-test.yml"
    source = workflow.read_text(encoding="utf-8")
    parsed = yaml.load(source, Loader=yaml.BaseLoader)
    assert set(parsed["on"]) == {"workflow_dispatch"}
    assert parsed["permissions"] == {"contents": "read"}
    matrix = parsed["jobs"]["clean-cloud-acceptance"]["strategy"]["matrix"]["include"]
    runners = {entry["runner"] for entry in matrix}
    assert runners == {"ubuntu-24.04", "windows-2025"}
    assert "pull_request" not in parsed["on"]
    assert "push" not in parsed["on"]
    assert "${{ secrets." not in source
    assert "persist-credentials: false" in source
    assert "actions/checkout@v6" in source
    assert "actions/setup-python@v6" in source
    assert "actions/upload-artifact@v6" in source


def test_cloud_workflow_runs_real_shortcut_runtime_and_data_checks():
    source = (ROOT / ".github" / "workflows" / "ultron-cloud-test.yml").read_text(encoding="utf-8")
    required = (
        "python -m pytest -q",
        "python -m unittest discover",
        "npm --prefix frontend run build",
        "cloud_shortcut_acceptance.py",
        "cloud_runtime_acceptance.py",
        "assert not Path('data').exists()",
        "cloud-test-results/pytest.xml",
        "Enforce all cloud acceptance gates",
    )
    for item in required:
        assert item in source


def test_cloud_scripts_are_isolated_keyless_and_honest_about_scope():
    runtime = (ROOT / ".github" / "scripts" / "cloud_runtime_acceptance.py").read_text(encoding="utf-8")
    shortcuts = (ROOT / ".github" / "scripts" / "cloud_shortcut_acceptance.py").read_text(encoding="utf-8")
    assert "ULTRON_HOME" in runtime
    assert "ULTRON_NO_BROWSER" in runtime
    assert "SENSITIVE_ENV_NAMES" in runtime
    assert "real_credentials_used" in runtime
    assert "backend_status" in runtime
    assert "frontend_status" in runtime
    assert "ports_released" in runtime
    assert "tempfile.mkdtemp" in runtime
    assert "tempfile.mkdtemp" in shortcuts
    assert "WindowStyle" in shortcuts
    assert "expected_terminal" in shortcuts
    assert "ultron-doctor.desktop" in shortcuts
    assert "ultron-env.desktop" in shortcuts
    assert "Ultron Doctor" in shortcuts
    assert "Open Ultron .env" in shortcuts
    assert "real_credentials_used" in shortcuts

"""Setuptools definition for a self-contained personal Ultron installation."""

from pathlib import Path

from setuptools import find_namespace_packages, setup


ROOT = Path(__file__).resolve().parent


def _requirements() -> list[str]:
    return [
        line.strip()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _runtime_data_files() -> list[tuple[str, list[str]]]:
    """Install non-Python runtime assets below sys.prefix/share/ultron."""
    groups: dict[str, list[str]] = {
        "share/ultron": [
            "config.yaml",
            "launcher.py",
            ".env.example",
            "SETUP_ULTRON_WINDOWS.bat",
            "SETUP_ULTRON_UBUNTU.sh",
            "start_ultron.bat",
            "start_ultron.sh",
        ],
        "share/ultron/images": [
            "images/ultron_icon.ico",
            "images/ultron_icon.png",
        ],
    }
    frontend = ROOT / "frontend"
    for path in sorted(frontend.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(frontend)
        if any(part in {"node_modules", "dist", ".vite"} for part in relative.parts):
            continue
        target = str(Path("share/ultron/frontend") / relative.parent)
        groups.setdefault(target, []).append(path.relative_to(ROOT).as_posix())
    return sorted(groups.items())


setup(
    name="ultron",
    version="1.0.0",
    packages=find_namespace_packages(include=["backend*"], exclude=["tests*"]),
    package_data={
        "backend.app.personalities": ["*.md"],
        "backend.app.skills": ["*.md"],
    },
    data_files=_runtime_data_files(),
    include_package_data=True,
    zip_safe=False,
    install_requires=_requirements(),
    entry_points={
        "console_scripts": [
            "ultron=backend.app.cli:main",
        ],
    },
    author="Arena AI & Debjeet",
    description="Ultron V1: Personal Developer Partner & Emotional Companion.",
    long_description=(ROOT / "README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    python_requires=">=3.10",
)

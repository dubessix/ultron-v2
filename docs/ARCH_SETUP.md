# Arch Linux / Linux Setup Notes

Use the general `SETUP_GUIDE.md`; these are package-manager examples for Arch-like systems.

```bash
sudo pacman -S python nodejs npm git
# optional media support
sudo pacman -S ffmpeg
```

Create an isolated environment:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m backend.app.cli setup
python -m backend.app.cli doctor
python -m backend.app.cli start --check
```

Start:

```bash
python launcher.py
```

or install the wheel and use `ultron start`.

The launcher requires Node 20.19+ or 22.12+, binds to `127.0.0.1`, and serves the production frontend at port 5173 by default. If browser dispatch is unavailable after both health checks pass, open `http://127.0.0.1:5173` manually.

Do not use `sudo pip`, do not run the assistant as root, and do not expose the ports on a public/LAN interface.

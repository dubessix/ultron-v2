"""V2 Step C acceptance on a real machine: close tab 10/10 and close app 10/10,
plus sleep / dedupe / reopen / history on real tabs.

Real Ultron backend + real Chromium with the Ultron extension loaded. Ultron's
own tab stays in front (as when the owner talks to him) and must never close.
Apps are real processes closed through the real confirmation flow.
Linux only (process names via symlink; Chromium extension support).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = "http://127.0.0.1:8000/api"
EXTENSION = ROOT / "extension" / "chrome"


def post(path: str, body: dict) -> dict:
    request = urllib.request.Request(f"{API}{path}", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 (loopback)
        return json.loads(response.read())


def get(path: str) -> dict:
    with urllib.request.urlopen(f"{API}{path}", timeout=10) as response:  # noqa: S310
        return json.loads(response.read())


def tool(tool_id: str, **arguments) -> dict:
    result = post("/tools/execute", {"tool_id": tool_id, "arguments": arguments, "session_id": "acceptance"})
    if result.get("status") == "PENDING_CONFIRMATION":  # one yes, like the owner saying "ok do"
        result = post("/tools/execute", {"tool_id": tool_id, "arguments": arguments, "session_id": "acceptance",
                                         "has_confirmed": True, "confirmation_token": result["confirmation_token"]})
    return result


class Pages(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        title = self.path.strip("/").replace("-", " ") or "Ultron"
        body = f"<html><head><title>{title}</title></head><body><p>Text of {title}.</p></body></html>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def serve(port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), Pages)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def wait(check, what: str, timeout: float = 60.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            value = check()
            if value:
                return value
        except Exception:
            pass
        time.sleep(0.3)
    raise SystemExit(f"FAILED waiting for {what}")


def titles(context) -> list[str]:
    return [page.title() for page in context.pages if not page.is_closed()]


def close_tab_rounds(context, ultron_page) -> int:
    passed = 0
    for i in range(1, 11):
        names = [f"round-{i}-lofi-YouTube", f"round-{i}-news-YouTube", f"round-{i}-docs"]
        for name in names:
            context.new_page().goto(f"http://127.0.0.1:8765/{name}")
        ultron_page.bring_to_front()  # the owner is talking to Ultron
        wait(lambda n=names: all(t in titles(context) for t in (x.replace("-", " ") for x in n)), "pages")
        ok = True

        r = tool("close_tab", which=f"round {i} lofi")
        ok &= bool(r.get("success")) and f"round {i} lofi YouTube" not in titles(context)

        r = tool("close_tab", which=f"round {i} youtube docs")  # nothing matches both -> honest no
        ok &= not r.get("success")

        r = tool("close_tab", which=f"round {i}")  # 2 match -> asks, closes nothing
        ok &= (not r.get("success")) and "match" in (r.get("error") or "") and len(titles(context)) == 3

        r = tool("close_tab", which=f"all round {i}")
        ok &= bool(r.get("success")) and titles(context) == ["Ultron"]

        context.new_page().goto(f"http://127.0.0.1:8765/round-{i}-extra")
        ultron_page.bring_to_front()
        r = tool("close_tab")  # "close this tab" while Ultron is in front
        ok &= bool(r.get("success")) and titles(context) == ["Ultron"]

        ok &= not ultron_page.is_closed()
        print(f"close tab round {i}: {'OK' if ok else 'FAIL'}", flush=True)
        passed += int(ok)
    return passed


def other_browser_checks(context, ultron_page) -> None:
    context.new_page().goto("http://127.0.0.1:8765/reading-page")
    ultron_page.bring_to_front()
    listed = tool("browser_tabs")
    assert listed["success"] and listed["data"]["count"] == 1, listed
    read = tool("read_current_page", which="reading")
    assert read["success"] and "Text of reading page" in read["data"]["content"], read
    switched = tool("browser_tabs", action="switch", which="reading")
    assert switched["success"], switched
    assert tool("refresh_page")["success"]
    everything = tool("close_browser")
    assert everything["success"] and titles(context) == ["Ultron"], everything
    print("list / read / switch / refresh / close all: OK", flush=True)


def listed_tabs() -> list[dict]:
    listed = tool("browser_tabs")
    assert listed["success"], listed
    return [tab for tab in listed["data"]["tabs"] if not tab["ultron"]]


def tab_extras_checks(chrome_binary: str, home: Path) -> None:
    """Sleep (free RAM), close duplicates, reopen closed, find in history.

    Runs in plain Chromium with NO automation attached: Playwright's debugger
    takes the whole test browser down when a tab is discarded (real Chrome is
    fine), so pages are opened from the command line on a virtual screen.
    """
    if not os.environ.get("DISPLAY"):
        raise SystemExit("FAILED: tab extras need a screen; run under xvfb-run")
    pages = [f"http://127.0.0.1:8765/{name}" for name in ("sleepy-alpha", "sleepy-beta", "dup-page", "dup-page")]
    chrome_log = open(home / "chrome-plain.log", "w")
    chrome = subprocess.Popen(
        # --no-sandbox as Playwright does (CI Ubuntu 24.04 blocks the sandbox); test pages are local only.
        [chrome_binary, f"--user-data-dir={home / 'chrome-plain'}", "--no-first-run", "--no-default-browser-check",
         "--no-sandbox",
         "--disable-features=DisableLoadExtensionCommandLineSwitch", f"--disable-extensions-except={EXTENSION}",
         f"--load-extension={EXTENSION}", "http://127.0.0.1:5173/", *pages],
        stdout=chrome_log, stderr=subprocess.STDOUT)
    try:
        try:
            wait(lambda: get("/browser/status").get("connected"), "extension to connect (plain Chromium)", 60)
        except SystemExit:
            chrome_log.flush()
            print("chromium log tail:\n" + (home / "chrome-plain.log").read_text(errors="replace")[-2000:], flush=True)
            raise
        wait(lambda: sorted(t["title"] for t in listed_tabs()) == ["dup page", "dup page", "sleepy alpha", "sleepy beta"],
             "4 tabs loaded")

        r = tool("browser_tabs", action="dedupe")
        assert r["success"] and r["data"]["closed"] == 1, r
        assert [t["title"] for t in listed_tabs()].count("dup page") == 1

        r = tool("browser_tabs", action="sleep")
        assert r["success"] and r["data"]["slept"] == 3, r
        wait(lambda: all(t["asleep"] for t in listed_tabs()), "tabs asleep")
        time.sleep(1)
        assert get("/browser/status")["connected"] and chrome.poll() is None, "helper or Chrome died after sleep"
        ultron = [t for t in tool("browser_tabs")["data"]["tabs"] if t["ultron"]]
        assert ultron and not ultron[0]["asleep"], "Ultron's own tab must never sleep"

        r = tool("close_tab", which="sleepy alpha")
        assert r["success"] and "sleepy alpha" not in [t["title"] for t in listed_tabs()], r
        r = tool("browser_tabs", action="reopen", which="alpha")
        assert r["success"] and r["data"]["reopened"]["url"].endswith("/sleepy-alpha"), r
        wait(lambda: any(t["url"].endswith("/sleepy-alpha") for t in listed_tabs()), "reopened tab")

        r = wait(lambda: (lambda h: h if h["success"] and h["data"]["count"] else None)(
            tool("browser_tabs", action="history", which="sleepy beta")), "history match", 30)
        assert r["data"]["matches"][0]["url"].endswith("/sleepy-beta"), r
        r = tool("browser_tabs", action="history", which="zzqq nothing like this")
        assert r["success"] and r["data"]["count"] == 0, r
        print("sleep / dedupe / reopen / history (plain Chromium): OK", flush=True)
    finally:
        chrome.terminate()
        try:
            chrome.wait(timeout=10)
        except subprocess.TimeoutExpired:
            chrome.kill()
        chrome_log.close()


def close_app_rounds(folder: Path) -> int:
    passed = 0
    for i in range(1, 11):
        name = f"ultronapp{i}"
        link = folder / name
        link.symlink_to(sys.executable)
        app = subprocess.Popen([str(link), "-c", "import time; print('up', flush=True); time.sleep(120)"],
                               stdout=subprocess.PIPE, text=True)
        app.stdout.readline()
        r = tool("apps", action="close", name=name)
        try:
            app.wait(timeout=8)
        except subprocess.TimeoutExpired:
            pass
        ok = bool(r.get("success")) and app.poll() is not None and r["data"].get("verified_gone")
        print(f"close app round {i}: {'OK' if ok else 'FAIL ' + json.dumps(r)[:300]}", flush=True)
        passed += int(ok)
        if app.poll() is None:
            app.kill()
    return passed


def stubborn_app(folder: Path) -> None:
    link = folder / "ultronstubborn"
    link.symlink_to(sys.executable)
    code = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('up', flush=True); time.sleep(120)"
    app = subprocess.Popen([str(link), "-c", code], stdout=subprocess.PIPE, text=True)
    app.stdout.readline()
    r = tool("apps", action="close", name="ultronstubborn")
    assert not r.get("success") and "still running" in r["error"] and app.poll() is None, r
    r = tool("apps", action="close", name="ultronstubborn", force=True)
    app.wait(timeout=8)
    assert r.get("success"), r
    print("stubborn app: honest 'still running', then force: OK", flush=True)


def main() -> int:
    from playwright.sync_api import sync_playwright

    home = Path(tempfile.mkdtemp(prefix="ultron-c-"))
    env = {**os.environ, "ULTRON_HOME": str(home), "PYTHONUNBUFFERED": "1"}
    log = open(home / "backend.log", "w")
    backend = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1",
                                "--port", "8000"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    servers = [serve(8765), serve(5173)]
    try:
        wait(lambda: get("/health"), "backend health", 120)
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                str(home / "chrome-profile"), channel="chromium", headless=True,
                args=[f"--disable-extensions-except={EXTENSION}", f"--load-extension={EXTENSION}"])
            ultron_page = context.pages[0] if context.pages else context.new_page()
            ultron_page.goto("http://127.0.0.1:5173/")
            wait(lambda: get("/browser/status").get("connected"), "extension to connect", 60)
            print("extension connected", flush=True)
            tabs_ok = close_tab_rounds(context, ultron_page)
            other_browser_checks(context, ultron_page)
            chrome_binary = p.chromium.executable_path
            context.close()
        wait(lambda: not get("/browser/status").get("connected"), "test browser to disconnect", 20)
        tab_extras_checks(chrome_binary, home)
        folder = home / "apps"
        folder.mkdir()
        apps_ok = close_app_rounds(folder)
        stubborn_app(folder)
        print(f"RESULT close tab {tabs_ok}/10, close app {apps_ok}/10", flush=True)
        return 0 if tabs_ok == 10 and apps_ok == 10 else 1
    finally:
        for server in servers:
            server.shutdown()
        backend.terminate()
        try:
            backend.wait(timeout=10)
        except subprocess.TimeoutExpired:
            backend.kill()
        log.close()
        tail = (home / "backend.log").read_text(errors="replace")[-3000:]
        if "Traceback" in tail:
            print("backend log tail:\n" + tail)


if __name__ == "__main__":
    sys.exit(main())

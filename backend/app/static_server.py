"""Loopback-only production static server for the built Ultron frontend."""

from __future__ import annotations

import argparse
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


class FrontendRequestHandler(SimpleHTTPRequestHandler):
    """Serve built assets, a health endpoint, and SPA index fallback."""

    server_version = "UltronFrontend/1.0"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/healthz":
            payload = json.dumps({"status": "healthy", "service": "ultron-frontend"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
            return

        requested = Path(unquote(path.lstrip("/")))
        target = Path(self.directory) / requested
        if path != "/" and not target.exists() and "." not in requested.name:
            self.path = "/index.html"
        super().do_GET()

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()


class LoopbackThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def create_server(directory: Path, host: str, port: int) -> LoopbackThreadingHTTPServer:
    root = Path(directory).expanduser().resolve(strict=True)
    if host not in _LOOPBACK_HOSTS:
        raise ValueError("Frontend server may bind only to a loopback host.")
    if not root.is_dir() or not (root / "index.html").is_file():
        raise FileNotFoundError(f"Frontend production build is missing index.html: {root}")
    handler = partial(FrontendRequestHandler, directory=str(root))
    return LoopbackThreadingHTTPServer((host, int(port)), handler)


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the built Ultron frontend on loopback only.")
    parser.add_argument("--directory", required=True)
    parser.add_argument("--host", default="127.0.0.1", choices=sorted(_LOOPBACK_HOSTS))
    parser.add_argument("--port", type=int, default=5173)
    args = parser.parse_args()

    server = create_server(Path(args.directory), args.host, args.port)
    actual_host, actual_port = server.server_address[:2]
    print(
        f"[FRONTEND] Serving production assets from {Path(args.directory).resolve()} "
        f"at http://{actual_host}:{actual_port}",
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

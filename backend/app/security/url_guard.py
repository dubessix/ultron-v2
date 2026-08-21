"""URL validation helpers for SSRF-safe server requests and browser launches."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

_BLOCKED_HOSTNAMES = {
    "localhost", "metadata", "metadata.google.internal", "169.254.169.254",
}
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".home", ".lan")
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 5


def _blocked_ip(address: str) -> bool:
    try:
        value = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return True
    return bool(
        value.is_private
        or value.is_loopback
        or value.is_link_local
        or value.is_reserved
        or value.is_multicast
        or value.is_unspecified
    )


def resolve_public_addresses(host: str, port: int | None = None) -> tuple[bool, str | None, set[str]]:
    """Resolve all addresses and fail closed if any answer is non-public."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False, "host does not resolve", set()
    except OSError:
        return False, "address lookup failed", set()
    addresses = {str(info[4][0]).split("%", 1)[0] for info in infos}
    if not addresses:
        return False, "host did not resolve to an address", set()
    blocked = sorted(address for address in addresses if _blocked_ip(address))
    if blocked:
        return False, f"non-public address blocked: {blocked[0]}", addresses
    return True, None, addresses


def validate_public_url_details(url: str) -> dict:
    """Validate a server-side outbound URL and return its approved DNS answers."""
    try:
        parsed = urlparse(str(url))
    except (TypeError, ValueError):
        return {"safe": False, "reason": "malformed URL", "addresses": set()}
    if parsed.scheme.lower() not in {"http", "https"}:
        return {"safe": False, "reason": "URL must be http(s)", "addresses": set()}
    if parsed.username or parsed.password:
        return {"safe": False, "reason": "credentials in URL are blocked", "addresses": set()}
    if not parsed.hostname:
        return {"safe": False, "reason": "URL has no host", "addresses": set()}

    host = parsed.hostname.lower().rstrip(".")
    if host in _BLOCKED_HOSTNAMES or host.endswith(_BLOCKED_SUFFIXES):
        return {"safe": False, "reason": f"local/metadata host blocked: {host}", "addresses": set()}
    try:
        port = parsed.port
    except ValueError:
        return {"safe": False, "reason": "invalid port", "addresses": set()}

    # IP literals are checked directly so DNS mocking/rebinding cannot turn a
    # loopback literal into an apparently public hostname.
    try:
        literal = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        literal = None
    if literal is not None:
        if _blocked_ip(str(literal)):
            return {"safe": False, "reason": f"non-public address blocked: {literal}", "addresses": {str(literal)}}
        ok, reason, addresses = True, None, {str(literal)}
    else:
        ok, reason, addresses = resolve_public_addresses(host, port)
    return {
        "safe": ok,
        "reason": reason,
        "addresses": addresses,
        "host": host,
        "port": port,
        "url": parsed.geturl(),
    }


def validate_public_url(url: str):
    details = validate_public_url_details(url)
    return bool(details["safe"]), details.get("reason")


def validate_redirect(current_url: str, location: str) -> dict:
    if not location:
        return {"safe": False, "reason": "redirect missing Location", "addresses": set()}
    return validate_public_url_details(urljoin(current_url, location))


def validate_browser_url(url: str) -> tuple[bool, str | None]:
    """Browser launches may use localhost, but never credentials or unsafe schemes."""
    try:
        parsed = urlparse(str(url))
    except (TypeError, ValueError):
        return False, "malformed URL"
    if parsed.scheme.lower() not in {"http", "https"}:
        return False, "browser URL must be http(s)"
    if parsed.username or parsed.password:
        return False, "credentials in URL are blocked"
    if not parsed.hostname:
        return False, "URL has no host"
    return True, None


def response_peer_is_approved(response, approved_addresses: set[str]) -> tuple[bool, str | None]:
    """Best-effort DNS-rebinding check against httpx's connected peer address."""
    stream = response.extensions.get("network_stream") if hasattr(response, "extensions") else None
    if stream is None:
        return True, None
    try:
        peer = stream.get_extra_info("server_addr")
    except Exception:
        return True, None
    if not peer:
        return True, None
    address = str(peer[0] if isinstance(peer, tuple) else peer).split("%", 1)[0]
    if _blocked_ip(address) or (approved_addresses and address not in approved_addresses):
        return False, f"connected peer failed DNS pin check: {address}"
    return True, None

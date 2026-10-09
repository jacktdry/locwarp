"""Enforce desktop-only APIs while retaining the opt-in phone LAN control page.

The peer address comes from the ASGI socket, not untrusted Host or forwarded
headers. This protects /api/device, /api/location, WebSocket joystick and user
configuration from other hosts when the backend listens on 0.0.0.0 for /phone.
"""
from __future__ import annotations

import ipaddress
import json

# Phone action endpoints still enforce X-LocWarp-Token in phone_control.py.
LAN_PHONE_ROUTES = frozenset({
    ("GET", "/phone"),
    ("GET", "/api/phone/_reach"),
    ("POST", "/api/phone/auth"),
    ("GET", "/api/phone/status"),
    ("POST", "/api/phone/teleport"),
    ("POST", "/api/phone/stop"),
    ("POST", "/api/phone/restore"),
    ("POST", "/api/phone/navigate"),
    ("GET", "/api/phone/geocode"),
})


def is_loopback_peer(host: str | None) -> bool:
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def allowed_from_peer(scope: dict) -> bool:
    client = scope.get("client")
    host = client[0] if client else None
    if is_loopback_peer(host):
        # A malicious webpage can attempt cross-origin requests against
        # localhost even without reading a CORS response. Reject explicit
        # foreign Origins before any mutating desktop route runs.
        if scope.get("type") == "http":
            headers = {k.lower(): v for k, v in scope.get("headers", [])}
            origin = headers.get(b"origin")
            if origin is not None and origin.decode("ascii", "ignore") not in {
                "null", "http://127.0.0.1:5173", "http://localhost:5173",
                "http://127.0.0.1:8777", "http://localhost:8777",
            }:
                return False
        return True
    # No remote WebSocket controls; phone page uses HTTPS-independent
    # same-origin fetch with a short PIN and a protected bearer token.
    return scope.get("type") == "http" and (scope.get("method"), scope.get("path")) in LAN_PHONE_ROUTES


class NetworkAccessGuard:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") not in ("http", "websocket") or allowed_from_peer(scope):
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008, "reason": "Loopback only"})
            return
        body = json.dumps({"detail": "Desktop API is available only on this computer"}).encode()
        await send({"type": "http.response.start", "status": 403, "headers": [
            (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
            (b"cache-control", b"no-store"),
        ]})
        await send({"type": "http.response.body", "body": body})

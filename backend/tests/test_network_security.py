"""Release security checks: ASGI-socket and PIN-state tests, no real phone."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import HTTPException

from core.network_guard import NetworkAccessGuard, allowed_from_peer, is_loopback_peer
from api.phone_control import _PinAttemptLimiter, _AuthRequest, _auth, phone_auth


class NetworkGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_desktop_routes_rejected_on_lan(self):
        for path in ("/api/device/list", "/api/location/status", "/api/location/teleport",
                     "/api/bookmarks", "/api/phone/info", "/api/phone/rotate",
                     "/openapi.json", "/docs"):
            self.assertFalse(allowed_from_peer({"type":"http", "client":("192.168.1.21", 3341),
                                                 "method":"GET", "path":path}),path)
        self.assertFalse(allowed_from_peer({"type":"websocket", "client":("192.168.1.21", 3341),
                                             "path":"/ws/status"}))

    async def test_phone_routes_allowlisted_only(self):
        for method,path in (("GET", "/phone"),("GET", "/api/phone/_reach"),
                            ("POST", "/api/phone/auth"),("GET", "/api/phone/status"),
                            ("POST", "/api/phone/teleport"), ("POST", "/api/phone/stop"),
                            ("POST", "/api/phone/restore"), ("POST", "/api/phone/navigate"),
                            ("GET", "/api/phone/geocode")):
            self.assertTrue(allowed_from_peer({"type":"http", "client":("192.168.1.21", 3341),
                                                "method":method, "path":path}),(method,path))
        self.assertFalse(allowed_from_peer({"type":"http", "client":("192.168.1.21", 3341),
                                             "method":"POST", "path":"/api/phone/info"}))

    async def test_socket_peer_not_spoofable_by_headers(self):
        scope={"type":"http", "method":"GET", "path":"/api/device/list", "client":("10.0.0.2", 333),
               "headers":[(b"host",b"127.0.0.1:8777"), (b"x-forwarded-for",b"127.0.0.1")]}
        self.assertFalse(allowed_from_peer(scope))
        for host in ('127.0.0.1','::1','::ffff:127.0.0.1'):
            self.assertTrue(is_loopback_peer(host))
        self.assertFalse(is_loopback_peer('localhost'))
        self.assertFalse(is_loopback_peer('10.0.0.2'))

    async def test_loopback_rejects_explicit_foreign_origin(self):
        scope={"type":"http", "method":"POST", "path":"/api/location/teleport",
               "client":("127.0.0.1", 444), "headers":[(b"origin", b"https://evil.example")]}
        self.assertFalse(allowed_from_peer(scope))
        scope['headers']=[(b"origin", b"null")]
        self.assertTrue(allowed_from_peer(scope))
        scope['headers']=[]
        self.assertTrue(allowed_from_peer(scope))

    async def test_asgi_denied_http_and_websocket_without_entering_app(self):
        called=[]
        async def inner(scope, recv, send):
            called.append(scope)
        guard=NetworkAccessGuard(inner)
        sends=[]
        async def send(m): sends.append(m)
        async def recv(): return {}
        await guard({"type":"http","method":"POST","path":"/api/location/teleport",
                     "client":("10.0.0.2",333)},recv,send)
        self.assertEqual(sends[0]['status'],403)
        sends.clear()
        await guard({"type":"websocket", "path":"/ws/status","client":("10.0.0.2",333)},recv,send)
        self.assertEqual(sends[0]['type'],"websocket.close")
        self.assertEqual(sends[0]['code'],1008)
        self.assertFalse(called)


class PinRateLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_peer_guess_limit_and_expiry(self):
        limiter=_PinAttemptLimiter()
        for _ in range(5): limiter.check_and_record('192.168.1.9',now=100.0)
        with self.assertRaises(HTTPException) as context:
            limiter.check_and_record('192.168.1.9',now=100.0)
        self.assertEqual(context.exception.status_code,429)
        limiter.check_and_record('192.168.1.9',now=160.1)
        limiter.reset()
        self.assertEqual(len(limiter.attempts),0)

    async def test_auth_requires_pin_and_rate_limits(self):
        limiter=_PinAttemptLimiter()
        client=SimpleNamespace(client=SimpleNamespace(host='10.1.2.3'))
        with patch('api.phone_control._pin_limiter',limiter):
            for _ in range(5):
                with self.assertRaises(HTTPException) as ctx:
                    await phone_auth(_AuthRequest(pin='111111'),client)
                self.assertEqual(ctx.exception.status_code,401)
            with self.assertRaises(HTTPException) as ctx:
                await phone_auth(_AuthRequest(pin=_auth.pin),client)
            self.assertEqual(ctx.exception.status_code,429)
            limiter.reset()
            granted=await phone_auth(_AuthRequest(pin=_auth.pin),client)
            self.assertEqual(granted['token'],_auth.token)

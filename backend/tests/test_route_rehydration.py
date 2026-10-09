"""Renderer rehydration: read-only route snapshots never touch device GPS."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from core.simulation_engine import SimulationEngine
from models.schemas import Coordinate, SimulationState


def active_engine():
    # Dummy location service; these tests must not connect to any phone.
    engine = SimulationEngine(object())
    engine.state = SimulationState.MULTI_STOP
    engine.current_position = Coordinate(lat=25.1, lng=121.2)
    engine._last_sim_kind = 'multi_stop'
    engine._last_sim_args = {'waypoints': [Coordinate(lat=25, lng=121), Coordinate(lat=26, lng=122)]}
    engine._last_route_path = [{'lat': 25.0, 'lng': 121.0}, {'lat': 25.1, 'lng': 121.2}]
    engine.distance_traveled = 120.0
    return engine


class RouteRehydrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_running_route_snapshot_is_fully_read_only(self):
        engine = active_engine()
        snapshot = engine.get_status()
        self.assertEqual(snapshot.state, SimulationState.MULTI_STOP)
        self.assertEqual(snapshot.simulation_kind, 'multi_stop')
        self.assertEqual(len(snapshot.route_path), 2)
        self.assertEqual(len(snapshot.waypoints), 2)
        self.assertEqual(snapshot.current_position.lat, 25.1)
        self.assertEqual(snapshot.distance_traveled, 120.0)
        snapshot.waypoints.append(Coordinate(lat=25.2, lng=121.2))
        snapshot.route_path.clear()
        self.assertEqual(len(engine._last_sim_args['waypoints']), 2)
        self.assertEqual(len(engine._last_route_path), 2)
        self.assertEqual(engine.state, SimulationState.MULTI_STOP)
        self.assertIsNone(engine._active_task)

    async def test_joystick_snapshot_does_not_reuse_stale_navigation_mode(self):
        engine = active_engine()
        engine.state = SimulationState.JOYSTICK
        self.assertEqual(engine.get_status().simulation_kind, 'joystick')

    async def test_paused_route_and_idle_cleanup(self):
        engine = active_engine()
        engine.state = SimulationState.PAUSED
        self.assertEqual(engine.get_status().simulation_kind, 'multi_stop')
        self.assertTrue(engine.get_status().is_paused)
        self.assertEqual(len(engine.get_status().route_path), 2)
        engine.state = SimulationState.IDLE
        snapshot = engine.get_status()
        self.assertEqual(snapshot.route_path, [])
        self.assertEqual(snapshot.waypoints, [])
        self.assertIsNone(snapshot.simulation_kind)

    async def test_aggregate_snapshot_two_devices_never_discovers_or_connects(self):
        from api.location import get_snapshot
        import main
        primary = active_engine()
        secondary = active_engine()
        secondary.current_position = Coordinate(lat=25.2, lng=121.3)
        fake = SimpleNamespace(_primary_udid='iphone-a', simulation_engines={
            'iphone-a': primary, 'iphone-b': secondary,
        })
        with patch.object(main, 'app_state', fake):
            response = await get_snapshot()
            self.assertEqual(response['primary_udid'], 'iphone-a')
            self.assertEqual(set(response['devices']), {'iphone-a', 'iphone-b'})
            self.assertEqual(response['devices']['iphone-a']['state'], 'multi_stop')
            self.assertEqual(response['devices']['iphone-b']['current_position']['lat'], 25.2)
            self.assertEqual(len(response['devices']['iphone-b']['route_path']), 2)
            # Also exercise the FastAPI endpoint and network guard.
            transport = httpx.ASGITransport(app=main.app, client=('127.0.0.1', 12345))
            async with httpx.AsyncClient(transport=transport, base_url='http://localhost:8777') as client:
                r = await client.get('/api/location/snapshot')
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.json()['primary_udid'], 'iphone-a')
        self.assertIsNone(primary._active_task)
        self.assertIsNone(secondary._active_task)

    async def test_remote_peer_cannot_read_snapshot(self):
        import main
        transport = httpx.ASGITransport(app=main.app, client=('192.168.2.5', 4321))
        async with httpx.AsyncClient(transport=transport, base_url='http://127.0.0.1:8777') as client:
            self.assertEqual((await client.get('/api/location/snapshot')).status_code, 403)

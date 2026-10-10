"""Hardware-free GUI UAT fixture regression tests. Never connect to iPhones."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


FIXTURE_PATH = Path(__file__).parent / 'fixtures' / 'fake_gui_route_backend.py'
spec = spec_from_file_location('fake_gui_route_backend', FIXTURE_PATH)
fake = module_from_spec(spec)
spec.loader.exec_module(fake)


class FakeGuiRouteTests(unittest.TestCase):
    def setUp(self):
        fake.STATE['phase'] = 'moving'
        fake.HTTP.clear()
        fake.WRITES.clear()
        self.client = TestClient(fake.app)

    def tearDown(self):
        self.client.close()
        fake.STATE['phase'] = 'moving'
        fake.WRITES.clear()

    def test_fake_devices_only_and_read_only_snapshot(self):
        devices = self.client.get('/api/device/list').json()
        self.assertEqual([d['udid'] for d in devices], [fake.A, fake.B])
        self.assertEqual([d['connection_type'] for d in devices], ['Network', 'USB'])
        self.assertTrue(all(d['is_connected'] for d in devices))
        with patch.object(fake, 'seconds', return_value=30.0):
            snapshot = self.client.get('/api/location/snapshot').json()
        self.assertEqual(snapshot['primary_udid'], fake.A)
        self.assertEqual(set(snapshot['devices']), {fake.A, fake.B})
        self.assertTrue(all(s['state'] == 'looping' for s in snapshot['devices'].values()))
        self.assertTrue(all(len(s['route_path']) == 4 for s in snapshot['devices'].values()))
        self.assertTrue(all(s['current_position'] for s in snapshot['devices'].values()))
        self.assertEqual(fake.WRITES, [])

    def test_route_completion_drops_overlays_without_disconnecting_fake_devices(self):
        response = self.client.get('/_uat/stop-route')
        self.assertEqual(response.json()['phase'], 'idle')
        snapshot = self.client.get('/api/location/snapshot').json()
        for state in snapshot['devices'].values():
            self.assertEqual(state['state'], 'idle')
            self.assertIsNone(state['current_position'])
            self.assertEqual(state['route_path'], [])
            self.assertEqual(state['waypoints'], [])
            self.assertIsNone(state['simulation_kind'])
        self.assertTrue(all(d['is_connected'] for d in self.client.get('/api/device/list').json()))

    def test_every_device_mutation_is_rejected_and_tracked(self):
        for method in ('post', 'put', 'patch', 'delete'):
            result = getattr(self.client, method)('/api/device/uat-fake-iphone-a/connect')
            self.assertEqual(result.status_code, 403)
            self.assertEqual(result.json()['error'], 'FAKE_BACKEND_MUTATIONS_FORBIDDEN')
        self.assertEqual(len(fake.WRITES), 4)
        self.assertEqual(self.client.get('/api/route/saved').json(), [])
        self.assertEqual(self.client.get('/api/route/categories').json(), [])
        self.assertEqual(self.client.get('/api/bookmarks/ui-state').json(), {'expanded_categories': []})

    def test_websocket_streams_synthetic_motion_without_hardware(self):
        with self.client.websocket_connect('/ws/status') as ws:
            first = ws.receive_json()
            second = ws.receive_json()
        self.assertEqual(first['type'], 'position_update')
        self.assertEqual(second['type'], 'position_update')
        self.assertEqual({first['data']['udid'], second['data']['udid']}, {fake.A, fake.B})
        self.assertTrue(all(isinstance(value['data']['lat'], float) for value in (first, second)))
        self.assertEqual(fake.WRITES, [])


if __name__ == '__main__':
    unittest.main()

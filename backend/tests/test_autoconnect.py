"""Opt-in supervisor/settings tests; transports, pairing and GPS are mocked."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import main
from api.device import AutoConnectRequest, set_auto_connect_setting
from core.device_manager import DeviceManager, _ActiveConnection


def record(udid, online=True):
    return {'udid': udid, 'name': udid, 'networkAdvertActive': online,
            'authState': {'rawCase': 'authenticated'}}


def state():
    app = main.AppState.__new__(main.AppState)
    app.device_manager = DeviceManager()
    app.simulation_engines = {}
    app._primary_udid = None
    app._auto_connect_udids = []
    app._last_position = None
    app.coord_formatter = SimpleNamespace(format=SimpleNamespace(value='decimal'))
    app._initial_map_position = None
    app._bookmark_expanded_categories = None
    app._geocode_provider = 'nominatim'
    app._google_geocode_key = ''
    app._wifi_keepalive_enabled = True
    return app


class AutoConnectTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = state()
        self.dm = self.app.device_manager
        self.contexts = []
        self.events = AsyncMock()
        self.sync = AsyncMock()
        patches = [
            patch.object(main, 'app_state', self.app),
            patch('core.device_manager.sys.platform', 'darwin'),
            patch('api.websocket.broadcast', self.events),
            patch.object(main, '_auto_sync_new_device_to_primary', self.sync),
            patch('core.device_manager._remember_device_name'),
            patch('pymobiledevice3.remote.native_tunnel.NativeRemotedTunnel', side_effect=self.handle),
            patch.object(self.dm, '_create_dvt_location_service', AsyncMock(side_effect=lambda conn, **kw: AsyncMock())),
            patch('pymobiledevice3.usbmux.list_devices', AsyncMock(return_value=[])),
            patch('core.device_manager.list_devices', AsyncMock(return_value=[])),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def handle(self, serial):
        context = AsyncMock()
        rsd = context.__aenter__.return_value
        rsd.product_version = '18.0'
        rsd.all_values = {'DeviceName': serial}
        rsd.peer_info = {}
        self.contexts.append((serial, context))
        return context

    async def asyncTearDown(self):
        await self.dm.disconnect_all()

    async def run_polls(self, records, *, after_tick=None):
        original_sleep = asyncio.sleep
        ticks = 0
        async def tick(_):
            nonlocal ticks
            # Let device tasks complete their bounded await chains, without
            # relying on elapsed wall-clock time or actual network traffic.
            for _ in range(40):
                await original_sleep(0)
            if after_tick:
                await after_tick(ticks)
            ticks += 1
            if ticks >= len(records):
                raise asyncio.CancelledError
        with patch.object(self.dm, '_mac_native_candidates', AsyncMock(side_effect=records)) as discover, patch(
            'asyncio.sleep', tick
        ):
            with self.assertRaises(asyncio.CancelledError):
                await main._mac_native_autoconnect_supervisor()
        return discover

    async def test_two_opted_in_devices_connect_and_unpinned_friend_is_excluded(self):
        self.app._auto_connect_udids = ['a', 'b']
        await self.run_polls([[record('a'), record('b'), record('friend')]])
        self.assertEqual(set(self.dm.connected_udids), {'a', 'b'})
        self.assertEqual({u for u, _ in self.contexts}, {'a', 'b'})
        self.assertEqual(self.sync.await_count, 2)
        connected = [c.args[1]['udid'] for c in self.events.await_args_list if c.args[0] == 'device_connected']
        self.assertEqual(set(connected), {'a', 'b'})

    async def test_offline_pin_reappears_on_next_paced_scan(self):
        self.app._auto_connect_udids = ['a']
        discover = await self.run_polls([[record('a', False)], [record('a')]])
        self.assertEqual(discover.await_count, 2)
        self.assertEqual([u for u, _ in self.contexts], ['a'])
        self.assertTrue(self.dm.is_connected('a'))

    async def test_no_opt_in_means_no_background_native_scan(self):
        await self.run_polls([[]])
        self.assertEqual(self.contexts, [])

    async def test_manual_disconnect_suppresses_opted_in_device(self):
        self.app._auto_connect_udids = ['a', 'b']
        self.dm.mark_user_disconnected('A')
        await self.run_polls([[record('a'), record('b')]])
        self.assertEqual(self.dm.connected_udids, ['b'])
        self.assertFalse(self.dm.auto_connect_allowed('a'))

    async def test_unpin_during_handshake_releases_unpublished_handle(self):
        self.app._auto_connect_udids = ['a']
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.handle
        def blocked(serial):
            context = original(serial)
            async def enter():
                entered.set()
                await release.wait()
                return context.__aenter__.return_value
            context.__aenter__.side_effect = enter
            return context
        async def unpin(tick):
            await entered.wait()
            self.app._auto_connect_udids = []
            release.set()
            for _ in range(10):
                await original_sleep(0)
        original_sleep = asyncio.sleep
        with patch('pymobiledevice3.remote.native_tunnel.NativeRemotedTunnel', side_effect=blocked):
            await self.run_polls([[record('a')]], after_tick=unpin)
        self.assertEqual(self.dm.connected_udids, [])
        self.contexts[0][1].__aexit__.assert_awaited_once()
        self.assertEqual(self.app.simulation_engines, {})

    async def test_three_device_cap_counts_inflight_manual_connections(self):
        self.app._auto_connect_udids = ['a', 'b', 'c']
        self.dm._connections['usb'] = _ActiveConnection('usb', AsyncMock(), '16.0')
        await self.run_polls([[record('a'), record('b'), record('c')]])
        self.assertEqual(len(self.dm.connected_udids), 3)
        self.assertIn('usb', self.dm.connected_udids)
        self.assertEqual(len(self.contexts), 2)

    async def test_failed_handshake_backs_off_without_repeat_storm(self):
        self.app._auto_connect_udids = ['a']
        def fail(serial):
            context = self.handle(serial)
            context.__aenter__.side_effect = ConnectionError('offline')
            return context
        with patch('pymobiledevice3.remote.native_tunnel.NativeRemotedTunnel', side_effect=fail), patch(
            'time.monotonic', return_value=100
        ):
            await self.run_polls([[record('a')], [record('a')]])
        self.assertEqual(len(self.contexts), 1)
        self.assertEqual(self.dm.connected_udids, [])
        self.contexts[0][1].__aexit__.assert_awaited_once()

    async def test_usb_priority_then_native_fallback_requires_opt_in(self):
        self.app._auto_connect_udids = ['a']
        lockdown = AsyncMock()
        lockdown.all_values = {'ProductVersion': '16.0', 'DeviceName': 'a'}
        raw = [SimpleNamespace(serial='a', connection_type='USB')]
        with patch('pymobiledevice3.usbmux.list_devices', AsyncMock(return_value=raw)), patch(
            'core.device_manager.list_devices', AsyncMock(return_value=raw)
        ), patch('core.device_manager.create_using_usbmux', AsyncMock(return_value=lockdown)), patch.object(
            self.dm, '_ensure_classic_ddi_mounted', AsyncMock()
        ):
            await self.run_polls([[record('a')]])
        self.assertEqual(self.dm.get_connection_type('a'), 'USB')
        self.assertEqual(self.contexts, [])
        # Model the existing USB watchdog's unplug teardown; it does not
        # mark user-disconnected. Supervisor may now use the native record.
        await self.dm.disconnect('a')
        self.app.simulation_engines.pop('a')
        await self.run_polls([[record('a'), record('friend')]])
        self.assertEqual(self.dm.get_connection_type('a'), 'Network')
        self.assertEqual([u for u, _ in self.contexts], ['a'])

    async def test_network_usbmux_entry_uses_native_without_lockdown_pair_prompt(self):
        self.app._auto_connect_udids = ['a']
        raw = [SimpleNamespace(serial='a', connection_type='Network')]
        with patch('pymobiledevice3.usbmux.list_devices', AsyncMock(return_value=raw)), patch(
            'core.device_manager.list_devices', AsyncMock(return_value=raw)
        ), patch('core.device_manager.create_using_usbmux', side_effect=AssertionError('no pairing prompt')):
            await self.run_polls([[record('a', False)]])
        self.assertEqual(self.dm.get_connection_type('a'), 'Network')

    async def test_mac_startup_yields_before_any_offline_discovery(self):
        async def parked():
            await asyncio.Event().wait()
        with patch.object(self.dm, 'discover_devices', side_effect=AssertionError('startup must not await discovery')), patch.object(
            main, '_mac_native_autoconnect_supervisor', parked
        ), patch.object(main, '_usbmux_presence_watchdog', parked), patch.object(
            main, '_wifi_tunnel_keepalive', parked
        ), patch.object(self.app, 'save_settings', return_value=True):
            async with main.lifespan(main.app):
                self.assertEqual(self.dm.connected_udids, [])

    async def test_persisted_udids_are_validated_deduplicated_and_capped(self):
        with patch('services.json_safe.safe_load_json', return_value={'auto_connect_udids': [
            'A', None, '../bad', 'a', 'b', 'c', 'd'], 'wifi_keepalive_enabled': False}):
            self.app._load_settings()
        self.assertEqual(self.app._auto_connect_udids, ['a', 'b', 'c'])
        self.assertFalse(self.app._wifi_keepalive_enabled)
        self.assertEqual(main.approved_udids('a'), [])
        self.assertEqual(main.approved_udids([False, '', 'a b']), [])

    async def test_settings_roundtrip_and_failed_write_rollback(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(main, 'SETTINGS_FILE', Path(directory) / 'settings.json'):
            await set_auto_connect_setting('A', AutoConnectRequest(enabled=True))
            persisted = json.loads((Path(directory) / 'settings.json').read_text())
            self.assertEqual(persisted['auto_connect_udids'], ['a'])
            self.assertIn('wifi_keepalive_enabled', persisted)
            self.app._auto_connect_udids = []
            self.app._load_settings()
            self.assertEqual(self.app._auto_connect_udids, ['a'])
        with patch.object(self.app, 'save_settings', return_value=False):
            from fastapi import HTTPException
            with self.assertRaises(HTTPException):
                await set_auto_connect_setting('b', AutoConnectRequest(enabled=True))
        self.assertEqual(self.app._auto_connect_udids, ['a'])

    async def test_local_settings_api_cap_invalid_payload_and_remote_denial(self):
        transport = httpx.ASGITransport(app=main.app, client=('127.0.0.1', 1234))
        with patch.object(self.app, 'save_settings', return_value=True):
            async with httpx.AsyncClient(transport=transport, base_url='http://localhost') as client:
                for udid in ('a', 'b', 'c'):
                    response = await client.post(f'/api/device/{udid}/auto-connect', json={'enabled': True})
                    self.assertEqual(response.status_code, 200)
                self.assertEqual((await client.post('/api/device/d/auto-connect', json={'enabled': True})).status_code, 409)
                self.assertEqual((await client.post('/api/device/a/auto-connect', json={'enabled': 'true'})).status_code, 422)
                self.assertEqual((await client.get('/api/device/a/auto-connect')).json()['enabled'], True)
                self.assertEqual((await client.get('/api/device/auto-connect')).json()['approved_udids'], ['a', 'b', 'c'])
        transport = httpx.ASGITransport(app=main.app, client=('192.168.1.3', 1234))
        async with httpx.AsyncClient(transport=transport, base_url='http://localhost') as client:
            self.assertEqual((await client.get('/api/device/auto-connect')).status_code, 403)
            self.assertEqual((await client.post('/api/device/a/auto-connect', json={'enabled': False})).status_code, 403)
        self.assertEqual(self.app._auto_connect_udids, ['a', 'b', 'c'])


    async def test_native_serial_case_is_preserved_while_approval_is_normalized(self):
        self.app._auto_connect_udids = ['device-a']
        await self.run_polls([[record('Device-A')]])
        self.assertEqual([u for u, _ in self.contexts], ['Device-A'])
        self.assertEqual(self.dm.connected_udids, ['Device-A'])
        self.assertIn('Device-A', self.app.simulation_engines)

    async def test_existing_manual_connection_is_not_rebuilt_or_auto_approved(self):
        self.app._auto_connect_udids = ['a']
        manual = _ActiveConnection('a', AsyncMock(), '18.0', connection_type='Network',
                                   tunnel_context=AsyncMock(), location_service=AsyncMock())
        original = self.dm.connect
        async def manual_wins(*args, **kwargs):
            self.dm._connections['a'] = manual
            await self.app.create_engine_for_device('a')
            return await original(*args, **kwargs)
        with patch.object(self.dm, 'connect', manual_wins):
            await self.run_polls([[record('a'), record('friend')]])
        self.assertIs(self.dm._connections['a'], manual)
        self.assertEqual(self.contexts, [])
        self.events.assert_not_awaited()
        self.assertEqual(self.app._auto_connect_udids, ['a'])

    async def test_manual_disconnect_during_service_setup_releases_all_handles(self):
        from api.device import disconnect_device
        self.app._auto_connect_udids = ['a']
        entered, release = asyncio.Event(), asyncio.Event()
        async def service(conn, **kwargs):
            conn.dvt_provider = AsyncMock()
            entered.set()
            await release.wait()
            return AsyncMock()
        original_sleep = asyncio.sleep
        async def disconnect(tick):
            await entered.wait()
            task = asyncio.create_task(disconnect_device('a'))
            await original_sleep(0)
            release.set()
            await task
        with patch.object(self.dm, '_create_dvt_location_service', service):
            await self.run_polls([[record('a')]], after_tick=disconnect)
        self.assertEqual(self.dm.connected_udids, [])
        self.assertEqual(self.app.simulation_engines, {})
        self.contexts[0][1].__aexit__.assert_awaited_once()
        self.assertFalse(self.dm.auto_connect_allowed('a'))


    async def test_usb_disappears_before_connect_without_reachable_native_record(self):
        self.app._auto_connect_udids = ['a']
        raw = [SimpleNamespace(serial='a', connection_type='USB')]
        with patch('pymobiledevice3.usbmux.list_devices', AsyncMock(return_value=raw)):
            await self.run_polls([[record('a', False)]])
        self.assertEqual(self.contexts, [])
        self.assertEqual(self.dm.connected_udids, [])

    async def test_unpaired_record_is_not_used_even_if_selected_and_advertising(self):
        self.app._auto_connect_udids = ['a']
        candidate = record('a')
        candidate['authState'] = {'rawCase': 'notAuthenticated'}
        await self.run_polls([[candidate]])
        self.assertEqual(self.contexts, [])
        self.assertEqual(self.dm.connected_udids, [])

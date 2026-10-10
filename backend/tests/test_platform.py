"""Transport ownership checks: mocks only, never connect to an iPhone."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from core.device_manager import DeviceManager
from core.wifi_tunnel import TunnelRunner


class PlatformTests(unittest.IsolatedAsyncioTestCase):
    async def test_mac_scans_native_paired_wifi_without_usbmux(self):
        records = [
            {'udid': 'device-a', 'name': 'Alpha', 'networkAdvertActive': True,
             'authState': {'rawCase': 'authenticated'}},
            {'udid': 'device-b', 'name': 'Beta', 'networkAdvertActive': False,
             'authState': {'rawCase': 'authenticated'}},
            {'udid': 'unpaired', 'name': 'Unknown', 'networkAdvertActive': True,
             'authState': {'rawCase': 'notAuthenticated'}},
        ]
        with patch('core.device_manager.sys.platform', 'darwin'), patch(
            'core.device_manager.list_devices', new_callable=AsyncMock, return_value=[]
        ), patch('pymobiledevice3.remote.native_tunnel.browse_native_devices', new_callable=AsyncMock,
                 return_value=records), patch('core.device_manager._load_device_name_cache', return_value={}):
            devices = await DeviceManager().discover_devices()
            self.assertEqual([d.udid for d in devices], ['device-a', 'device-b'])
            self.assertTrue(all(d.connection_type == 'Network' and not d.is_connected for d in devices))

    async def test_mac_connect_native_record_without_usbmux(self):
        records = [{'udid': 'device-a', 'name': 'Alpha', 'networkAdvertActive': True,
                    'authState': {'rawCase': 'authenticated'}}]
        tunnel = AsyncMock()
        tunnel.__aenter__.return_value.product_version = '27.0.1'
        tunnel.__aenter__.return_value.all_values = {'DeviceName': 'Alpha'}
        tunnel.__aenter__.return_value.peer_info = {'Properties': {'OSVersion': '27.0.1'}}
        with patch('core.device_manager.sys.platform', 'darwin'), patch(
            'core.device_manager.list_devices', new_callable=AsyncMock, return_value=[]
        ), patch('pymobiledevice3.remote.native_tunnel.browse_native_devices',
                 new_callable=AsyncMock, return_value=records), patch(
            'pymobiledevice3.remote.native_tunnel.NativeRemotedTunnel', return_value=tunnel
        ) as native, patch('core.device_manager.create_using_usbmux', new_callable=AsyncMock) as lockdown, patch(
            'core.device_manager._remember_device_name'
        ):
            dm = DeviceManager()
            await dm.connect('device-a')
            native.assert_called_once_with(serial='device-a')
            lockdown.assert_not_called()
            self.assertEqual(dm._connections['device-a'].ios_version, '27.0.1')
            self.assertEqual(dm._connections['device-a'].connection_type, 'Network')
            await dm.disconnect('device-a')
            tunnel.__aexit__.assert_awaited_once()

    async def test_mac_rejects_unpaired_native_record(self):
        with patch('core.device_manager.sys.platform', 'darwin'), patch(
            'core.device_manager.list_devices', new_callable=AsyncMock, return_value=[]
        ), patch('pymobiledevice3.remote.native_tunnel.browse_native_devices',
                 new_callable=AsyncMock, return_value=[]), patch(
            'pymobiledevice3.remote.native_tunnel.NativeRemotedTunnel'
        ) as native:
            with self.assertRaisesRegex(RuntimeError, '找不到已配對'):
                await DeviceManager().connect('unknown')
            native.assert_not_called()

    async def test_mac_legacy_bonjour_discover_disabled(self):
        from api.device import wifi_tunnel_discover
        with patch('api.device.sys.platform', 'darwin'), patch(
            'pymobiledevice3.bonjour.browse_remotepairing'
        ) as browse:
            self.assertEqual(await wifi_tunnel_discover(), {'devices': []})
            browse.assert_not_called()

    async def test_mac_remote_pair_repair_rejected_before_record_mutation(self):
        from api.device import wifi_repair
        from fastapi import HTTPException
        with patch('api.device.sys.platform', 'darwin'):
            with self.assertRaises(HTTPException) as raised:
                await wifi_repair()
            self.assertEqual(raised.exception.status_code, 400)
            self.assertEqual(raised.exception.detail['code'], 'mac_pair_via_finder')

    async def test_mac_usb_owns_no_root_handle_until_disconnect(self):
        handle = AsyncMock()
        rsd = handle.__aenter__.return_value
        lockdown = AsyncMock()
        with patch('core.device_manager.sys.platform', 'darwin'), patch(
            'pymobiledevice3.remote.rsd_tunnel.PreferredRsdTunnel', return_value=handle
        ) as factory, patch('core.device_manager.CoreDeviceTunnelProxy.create') as kernel:
            dm = DeviceManager()
            conn = await dm._connect_tunnel('test-udid', lockdown, '18.0')
            factory.assert_called_once_with(serial='test-udid', autopair=False)
            kernel.assert_not_called()
            self.assertIs(conn.rsd, rsd)
            self.assertIs(conn.usbmux_lockdown, lockdown)
            self.assertIs(conn.tunnel_context, handle)
            dm._connections['test-udid'] = conn
            await dm.disconnect('test-udid')
            handle.__aexit__.assert_awaited_once()

    async def test_mac_network_uses_native_remoted_and_owns_handle(self):
        handle = AsyncMock()
        rsd = handle.__aenter__.return_value
        lockdown = AsyncMock()
        with patch('core.device_manager.sys.platform', 'darwin'), patch(
            'pymobiledevice3.remote.native_tunnel.NativeRemotedTunnel', return_value=handle
        ) as native, patch(
            'pymobiledevice3.remote.rsd_tunnel.PreferredRsdTunnel'
        ) as usb:
            dm = DeviceManager()
            conn = await dm._connect_tunnel('test-udid', lockdown, '27.0.1', 'Network')
            native.assert_called_once_with(serial='test-udid')
            usb.assert_not_called()
            self.assertIs(conn.rsd, rsd)
            self.assertIs(conn.tunnel_context, handle)
            self.assertIs(conn.usbmux_lockdown, lockdown)
            dm._connections['test-udid'] = conn
            await dm.disconnect('test-udid')
            handle.__aexit__.assert_awaited_once()

    async def test_mac_network_native_failure_is_actionable(self):
        handle = AsyncMock()
        handle.__aenter__.side_effect = ConnectionError('temporary Wi-Fi loss')
        with patch('core.device_manager.sys.platform', 'darwin'), patch(
            'pymobiledevice3.remote.native_tunnel.NativeRemotedTunnel', return_value=handle
        ), patch('pymobiledevice3.remote.rsd_tunnel.PreferredRsdTunnel') as usb:
            with self.assertRaisesRegex(RuntimeError, 'macOS Wi-Fi native tunnel failed'):
                await DeviceManager()._connect_tunnel('test-udid', object(), '27.0.1', 'Network')
            usb.assert_not_called()

    async def test_mac_connect_routes_network_type_to_native(self):
        from types import SimpleNamespace
        lockdown = AsyncMock()
        lockdown.all_values = {'ProductVersion': '27.0.1', 'DeviceName': 'Test iPhone'}
        handle = AsyncMock()
        with patch('core.device_manager.sys.platform', 'darwin'), patch(
            'core.device_manager.list_devices', new_callable=AsyncMock,
            return_value=[SimpleNamespace(serial='test-udid', connection_type='Network')]
        ), patch('core.device_manager.create_using_usbmux', new_callable=AsyncMock, return_value=lockdown), patch(
            'core.device_manager._remember_device_name'
        ), patch('pymobiledevice3.remote.native_tunnel.NativeRemotedTunnel', return_value=handle) as native:
            dm = DeviceManager()
            await dm.connect('test-udid')
            native.assert_called_once_with(serial='test-udid')
            self.assertEqual(dm._connections['test-udid'].connection_type, 'Network')
            await dm.disconnect('test-udid')

    async def test_windows_keeps_kernel_proxy(self):
        proxy = AsyncMock()
        context = AsyncMock()
        proxy.start_tcp_tunnel = lambda: context
        with patch('core.device_manager.sys.platform', 'win32'), patch(
            'core.device_manager.CoreDeviceTunnelProxy.create', return_value=proxy
        ) as factory, patch('core.device_manager.RemoteServiceDiscoveryService', return_value=AsyncMock()):
            conn = await DeviceManager()._connect_tunnel('test-udid', object(), '18.0')
            factory.assert_awaited_once()
            self.assertIs(conn.tunnel_proxy, proxy)
            self.assertIs(conn.tunnel_context, context)

    async def test_mac_wifi_fails_before_pairing_without_privilege(self):
        with patch('core.wifi_tunnel.sys.platform', 'darwin'), patch(
            'core.wifi_tunnel.os.geteuid', return_value=501, create=True
        ), patch('pymobiledevice3.remote.tunnel_service.create_core_device_tunnel_service_using_remotepairing') as pair:
            runner = TunnelRunner()
            with self.assertRaisesRegex(PermissionError, 'macOS Wi-Fi'):
                await runner.start('test-udid', '192.0.2.1', 1234)
            pair.assert_not_called()
            self.assertFalse(runner.is_running())
            self.assertIsNone(runner.info)


class ConnectionSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dm = DeviceManager()
        self.handles = {u: AsyncMock() for u in ('a', 'b')}
        self.lockdowns = {u: AsyncMock() for u in ('a', 'b')}
        for lockdown in self.lockdowns.values():
            lockdown.all_values = {'ProductVersion': '18.0', 'DeviceName': 'Test'}
        patches = [
            patch('core.device_manager.sys.platform', 'darwin'),
            patch('core.device_manager.list_devices', AsyncMock(return_value=[
                SimpleNamespace(serial=u, connection_type='USB') for u in ('a', 'b')])),
            patch('core.device_manager.create_using_usbmux', AsyncMock(
                side_effect=lambda serial: self.lockdowns[serial.lower()])),
            patch('core.device_manager._remember_device_name'),
            patch('pymobiledevice3.remote.rsd_tunnel.PreferredRsdTunnel',
                  side_effect=lambda serial, autopair: self.handles[serial.lower()]),
            patch('pymobiledevice3.remote.native_tunnel.NativeRemotedTunnel',
                  side_effect=lambda serial: self.handles[serial.lower()]),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    async def asyncTearDown(self):
        await self.dm.disconnect_all()

    def gated_handshake(self, udid):
        entered, release = asyncio.Event(), asyncio.Event()
        async def enter():
            entered.set()
            await release.wait()
            return self.handles[udid].__aenter__.return_value
        self.handles[udid].__aenter__.side_effect = enter
        return entered, release

    async def test_same_udid_and_case_variant_open_only_one_tunnel(self):
        entered, release = self.gated_handshake('a')
        first = asyncio.create_task(self.dm.connect('a'))
        await entered.wait()
        second = asyncio.create_task(self.dm.connect('A'))
        await asyncio.sleep(0)
        self.handles['a'].__aenter__.assert_awaited_once()
        release.set()
        await asyncio.gather(first, second)
        self.assertEqual(self.dm.connected_udids, ['a'])
        await self.dm.disconnect('A')
        self.handles['a'].__aexit__.assert_awaited_once()
        self.lockdowns['a'].close.assert_awaited_once()

    async def test_other_device_connects_while_first_handshake_is_blocked(self):
        entered, release = self.gated_handshake('a')
        first = asyncio.create_task(self.dm.connect('a'))
        await entered.wait()
        try:
            await asyncio.wait_for(self.dm.connect('b'), 1)
            self.assertTrue(self.dm.is_connected('b'))
            self.assertFalse(first.done())
        finally:
            release.set()
            await first

    async def test_api_disconnect_invalidates_handshake_and_queued_connect(self):
        from api.device import disconnect_device, connect_device
        import main
        entered, release = self.gated_handshake('a')
        first = asyncio.create_task(self.dm.connect('a'))
        await entered.wait()
        queued = asyncio.create_task(self.dm.connect('a'))
        await asyncio.sleep(0)
        state = SimpleNamespace(device_manager=self.dm, simulation_engines={}, _primary_udid=None,
                                create_engine_for_device=AsyncMock())
        with patch.object(main, 'app_state', state), patch('api.websocket.broadcast', AsyncMock()), patch.object(
            self.dm, 'discover_devices', AsyncMock(return_value=[])
        ):
            disconnect = asyncio.create_task(disconnect_device('a'))
            await asyncio.sleep(0)
            self.assertFalse(self.dm.auto_connect_allowed('A'))
            release.set()
            results = await asyncio.gather(first, queued, return_exceptions=True)
            self.assertTrue(all(isinstance(r, ConnectionAbortedError) for r in results))
            await disconnect
            self.assertEqual(self.dm.connected_udids, [])
            self.handles['a'].__aexit__.assert_awaited_once()
            with self.assertRaises(ConnectionAbortedError):
                await self.dm.connect('a')
            await connect_device('a')
            self.assertTrue(self.dm.is_connected('a'))
            self.assertTrue(self.dm.auto_connect_allowed('a'))

    async def test_cancelled_handshake_releases_partial_context_and_allows_retry(self):
        entered, release = self.gated_handshake('a')
        task = asyncio.create_task(self.dm.connect('a'))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.dm.connected_udids, [])
        self.handles['a'].__aexit__.assert_awaited_once()
        self.lockdowns['a'].close.assert_awaited_once()
        release.set()
        await self.dm.connect('a')
        self.assertTrue(self.dm.is_connected('a'))

    async def test_failed_handshake_releases_partial_context_and_lockdown(self):
        self.handles['a'].__aenter__.side_effect = ConnectionError('handshake failed')
        with self.assertRaisesRegex(RuntimeError, 'macOS USB tunnel failed'):
            await self.dm.connect('a')
        self.handles['a'].__aexit__.assert_awaited_once()
        self.lockdowns['a'].close.assert_awaited_once()
        self.assertEqual(self.dm.connected_udids, [])

    async def test_cancelled_disconnect_finishes_cleanup_before_unlock(self):
        await self.dm.connect('a')
        entered, release = asyncio.Event(), asyncio.Event()
        async def exit(*args):
            entered.set()
            await release.wait()
        self.handles['a'].__aexit__.side_effect = exit
        task = asyncio.create_task(self.dm.disconnect('a'))
        await entered.wait()
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.lockdowns['a'].close.assert_awaited_once()
        self.assertEqual(self.dm.connected_udids, [])

    async def test_watchdog_preserves_manual_intent_across_polls_and_replug(self):
        import main
        from api.device import disconnect_device
        state = SimpleNamespace(device_manager=self.dm, simulation_engines={}, _primary_udid=None,
                                create_engine_for_device=AsyncMock())
        self.dm.discover_devices = AsyncMock(return_value=[])
        polls = [
            [SimpleNamespace(serial='A', connection_type='USB')],
            [], [], [],
            [SimpleNamespace(serial='a', connection_type='USB'),
             SimpleNamespace(serial='b', connection_type='USB')],
        ]
        tick = 0
        async def sleep(_):
            nonlocal tick
            if tick == len(polls):
                raise asyncio.CancelledError
            tick += 1
        with patch.object(main, 'app_state', state), patch('api.websocket.broadcast', AsyncMock()), patch.object(
            main, '_auto_sync_new_device_to_primary', AsyncMock()
        ), patch('pymobiledevice3.usbmux.list_devices', AsyncMock(side_effect=polls)), patch(
            'time.monotonic', return_value=1000
        ):
            await disconnect_device('a')
            with patch('asyncio.sleep', sleep):
                with self.assertRaises(asyncio.CancelledError):
                    await main._usbmux_presence_watchdog()
        self.handles['a'].__aenter__.assert_not_awaited()
        self.assertEqual(self.dm.connected_udids, ['b'])
        state.create_engine_for_device.assert_awaited_once_with('b')

    async def test_native_wifi_user_disconnect_closes_only_target(self):
        from api.device import disconnect_device
        import main
        await self.dm.connect('a')
        await self.dm.connect('b')
        self.dm._connections['a'].connection_type = 'Network'
        state = SimpleNamespace(device_manager=self.dm, simulation_engines={}, _primary_udid=None)
        with patch.object(main, 'app_state', state), patch('api.websocket.broadcast', AsyncMock()):
            await disconnect_device('a')
        self.assertEqual(self.dm.connected_udids, ['b'])
        self.assertFalse(self.dm.auto_connect_allowed('a'))
        self.handles['a'].__aexit__.assert_awaited_once()
        self.handles['b'].__aexit__.assert_not_awaited()


    async def test_native_post_handshake_validation_failure_releases_handle(self):
        handle = AsyncMock()
        handle.__aenter__.return_value.product_version = '16.0'
        with patch('core.device_manager.list_devices', AsyncMock(return_value=[])), patch.object(
            self.dm, '_mac_native_candidates', AsyncMock(return_value=[{'udid': 'a'}])
        ), patch('pymobiledevice3.remote.native_tunnel.NativeRemotedTunnel', return_value=handle):
            from core.device_manager import UnsupportedIosVersionError
            with self.assertRaises(UnsupportedIosVersionError):
                await self.dm.connect('a')
        handle.__aexit__.assert_awaited_once()
        self.assertEqual(self.dm.connected_udids, [])

    async def test_startup_discovery_and_normal_unplug_replug_remain_enabled(self):
        import main
        state = SimpleNamespace(device_manager=self.dm, simulation_engines={}, _primary_udid=None,
                                create_engine_for_device=AsyncMock())
        self.dm.discover_devices = AsyncMock(return_value=[])
        present = [SimpleNamespace(serial='b', connection_type='USB')]
        polls = [present, [], [], [], present]
        tick = 0
        async def sleep(_):
            nonlocal tick
            if tick == len(polls):
                raise asyncio.CancelledError
            tick += 1
        with patch.object(main, 'app_state', state), patch('api.websocket.broadcast', AsyncMock()), patch.object(
            main, '_auto_sync_new_device_to_primary', AsyncMock()
        ), patch('pymobiledevice3.usbmux.list_devices', AsyncMock(side_effect=polls)), patch(
            'time.monotonic', return_value=1000
        ), patch('asyncio.sleep', sleep):
            with self.assertRaises(asyncio.CancelledError):
                await main._usbmux_presence_watchdog()
        self.assertEqual(self.dm.connected_udids, ['b'])
        self.handles['b'].__aenter__.assert_has_awaits([unittest.mock.call(), unittest.mock.call()])
        self.handles['b'].__aexit__.assert_awaited_once()
        self.assertEqual(state.create_engine_for_device.await_count, 2)


    async def test_kernel_rsd_failure_closes_rsd_context_and_async_proxy(self):
        proxy, context, rsd = AsyncMock(), AsyncMock(), AsyncMock()
        proxy.start_tcp_tunnel = lambda: context
        rsd.connect.side_effect = ConnectionError('RSD handshake failed')
        with patch('core.device_manager.sys.platform', 'win32'), patch(
            'core.device_manager.CoreDeviceTunnelProxy.create', AsyncMock(return_value=proxy)
        ), patch('core.device_manager.RemoteServiceDiscoveryService', return_value=rsd):
            with self.assertRaises(RuntimeError):
                await self.dm.connect('a')
        rsd.close.assert_awaited_once()
        context.__aexit__.assert_awaited_once()
        proxy.close.assert_awaited_once()
        self.lockdowns['a'].close.assert_awaited_once()
        self.assertEqual(self.dm.connected_udids, [])

    async def test_second_usb_uses_native_and_keeps_first_userspace_connected(self):
        with patch('pymobiledevice3.remote.rsd_tunnel.PreferredRsdTunnel',
                   side_effect=lambda serial, autopair: self.handles[serial]) as preferred, patch(
            'pymobiledevice3.remote.native_tunnel.NativeRemotedTunnel',
            side_effect=lambda serial: self.handles[serial]
        ) as native:
            await self.dm.connect('a')
            first = self.dm._connections['a']
            await self.dm.connect('b')
            preferred.assert_called_once_with(serial='a', autopair=False)
            native.assert_called_once_with(serial='b')
            self.assertIs(self.dm._connections['a'], first)
            self.assertEqual(self.dm.get_connection_type('b'), 'USB')
            self.handles['a'].__aexit__.assert_not_awaited()
            await self.dm.disconnect('b')
            self.handles['b'].__aexit__.assert_awaited_once()
            self.handles['a'].__aexit__.assert_not_awaited()

    async def test_second_usb_native_failure_cleans_only_second_handle(self):
        await self.dm.connect('a')
        first = self.dm._connections['a']
        self.handles['b'].__aenter__.side_effect = ConnectionError('native unavailable')
        with patch('pymobiledevice3.remote.rsd_tunnel.PreferredRsdTunnel') as preferred, patch(
            'core.device_manager.CoreDeviceTunnelProxy.create'
        ) as privileged:
            with self.assertRaisesRegex(RuntimeError, 'second USB native tunnel failed'):
                await self.dm.connect('b')
            preferred.assert_not_called()
            privileged.assert_not_called()
        self.assertEqual(self.dm.connected_udids, ['a'])
        self.assertIs(self.dm._connections['a'], first)
        self.handles['b'].__aexit__.assert_awaited_once()
        self.lockdowns['b'].close.assert_awaited_once()
        self.handles['a'].__aexit__.assert_not_awaited()

    async def test_usb_legacy_and_native_wifi_do_not_occupy_userspace(self):
        from core.device_manager import _ActiveConnection
        self.dm._connections['legacy'] = _ActiveConnection('legacy', AsyncMock(), '16.0')
        self.dm._connections['wifi'] = _ActiveConnection('wifi', AsyncMock(), '18.0',
                                                       connection_type='Network', tunnel_context=AsyncMock())
        with patch('pymobiledevice3.remote.rsd_tunnel.PreferredRsdTunnel', return_value=self.handles['a']) as preferred, patch(
            'pymobiledevice3.remote.native_tunnel.NativeRemotedTunnel'
        ) as native:
            await self.dm.connect('a')
            preferred.assert_called_once_with(serial='a', autopair=False)
            native.assert_not_called()

    async def test_disconnect_userspace_owner_restores_first_usb_selection(self):
        await self.dm.connect('a')
        await self.dm.disconnect('a')
        with patch('pymobiledevice3.remote.rsd_tunnel.PreferredRsdTunnel', return_value=self.handles['b']) as preferred, patch(
            'pymobiledevice3.remote.native_tunnel.NativeRemotedTunnel'
        ) as native:
            await self.dm.connect('b')
            preferred.assert_called_once_with(serial='b', autopair=False)
            native.assert_not_called()

    async def test_concurrent_usb_handshakes_reserve_only_one_userspace_slot(self):
        entered, release = self.gated_handshake('a')
        first = asyncio.create_task(self.dm.connect('a'))
        await entered.wait()
        try:
            with patch('pymobiledevice3.remote.rsd_tunnel.PreferredRsdTunnel') as preferred:
                await asyncio.wait_for(self.dm.connect('b'), 1)
                preferred.assert_not_called()
            self.assertFalse(first.done())
        finally:
            release.set()
            await first
        self.assertEqual(set(self.dm.connected_udids), {'a', 'b'})

    async def test_preferred_native_fallback_does_not_reserve_userspace_slot(self):
        # Preferred's concrete handle identifies a native fallback, without
        # needing a second transport or a physical phone in this test.
        NativeRemotedTunnel = type('NativeRemotedTunnel', (), {})
        self.handles['a']._handle = NativeRemotedTunnel()
        await self.dm.connect('a')
        with patch('pymobiledevice3.remote.rsd_tunnel.PreferredRsdTunnel', return_value=self.handles['b']) as preferred:
            await self.dm.connect('b')
            preferred.assert_called_once_with(serial='b', autopair=False)
        self.handles['a'].__aexit__.assert_not_awaited()

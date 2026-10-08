"""Transport ownership checks: mocks only, never connect to an iPhone."""
import unittest
from unittest.mock import AsyncMock, patch

from core.device_manager import DeviceManager
from core.wifi_tunnel import TunnelRunner


class PlatformTests(unittest.IsolatedAsyncioTestCase):
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
        lockdown = object()
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
        lockdown = object()
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

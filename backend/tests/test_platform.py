"""Transport ownership checks: mocks only, never connect to an iPhone."""
import unittest
from unittest.mock import AsyncMock, patch

from core.device_manager import DeviceManager
from core.wifi_tunnel import TunnelRunner


class PlatformTests(unittest.IsolatedAsyncioTestCase):
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

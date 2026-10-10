"""Safe native Wi-Fi -> USB preference regressions. All transports are mocked."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import main
from core.device_manager import DeviceManager, _ActiveConnection
from models.schemas import Coordinate, SimulationState
from services.location_service import DvtLocationService


class UsbPreferenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.dm = DeviceManager()
        self.old_tunnel = AsyncMock()
        self.old_service = DvtLocationService(AsyncMock())
        self.old = _ActiveConnection('b', AsyncMock(), '27.0.1',
                                     connection_type='Network',
                                     location_service=self.old_service,
                                     tunnel_context=self.old_tunnel)
        self.sibling = _ActiveConnection('a', AsyncMock(), '27.0.1',
                                          connection_type='Network',
                                          location_service=DvtLocationService(AsyncMock()),
                                          tunnel_context=AsyncMock())
        self.dm._connections = {'a': self.sibling, 'b': self.old}
        self.new = _ActiveConnection('b', AsyncMock(), '27.0.1',
                                     connection_type='USB',
                                     dvt_provider=AsyncMock(),
                                     tunnel_context=AsyncMock())
        self.new_service = DvtLocationService(AsyncMock())
        self.engine = SimpleNamespace(state=SimulationState.IDLE, current_position=None,
                                      location_service=self.old_service, _active_task=None)
        self.app = SimpleNamespace(device_manager=self.dm, simulation_engines={'b': self.engine},
                                   _auto_connect_udids=['b'])
        async def replaced(udid, replace=False):
            self.assertEqual(udid, 'b')
            self.assertTrue(replace)
            self.app.simulation_engines['b'] = SimpleNamespace(
                state=SimulationState.IDLE, current_position=None,
                location_service=self.dm._connections[udid].location_service,
                _active_task=None)
        self.app.create_engine_for_device = AsyncMock(side_effect=replaced)
        self.events = AsyncMock()

    async def _poll_once(self):
        count = 0
        async def sleep(_):
            nonlocal count
            count += 1
            if count >= 2:
                raise asyncio.CancelledError
        with patch.object(main, 'app_state', self.app), patch('api.websocket.broadcast', self.events), patch(
            'pymobiledevice3.usbmux.list_devices', AsyncMock(
                return_value=[SimpleNamespace(serial='b', connection_type='USB')]
            )
        ), patch('asyncio.sleep', sleep):
            with self.assertRaises(asyncio.CancelledError):
                await main._usbmux_presence_watchdog()

    async def test_idle_native_wifi_is_replaced_by_verified_usb_without_affecting_sibling(self):
        with patch.object(self.dm, '_open_connection', AsyncMock(return_value=self.new)) as open_usb, patch.object(
            self.dm, '_create_dvt_location_service', AsyncMock(return_value=self.new_service)
        ) as dvt:
            await self._poll_once()
        open_usb.assert_awaited_once_with('b')
        self.assertIs(self.dm._connections['b'], self.new)
        self.assertIs(self.dm._connections['a'], self.sibling)
        self.assertIs(self.app.simulation_engines['b'].location_service, self.new_service)
        self.assertEqual(self.dm.get_connection_type('b'), 'USB')
        dvt.assert_awaited_once_with(self.new, strict=True)
        self.old_tunnel.__aexit__.assert_awaited_once()
        self.sibling.tunnel_context.__aexit__.assert_not_awaited()
        self.assertEqual([x.args[1]['connection_type'] for x in self.events.await_args_list
                          if x.args[0]=='device_connected'], ['USB'])
        self.assertFalse(self.old_service._active)

    async def test_failed_usb_handshake_keeps_existing_network_and_engine(self):
        with patch.object(self.dm, '_open_connection', AsyncMock(side_effect=ConnectionError('USB handshake'))):
            await self._poll_once()
        self.assertIs(self.dm._connections['b'], self.old)
        self.assertIs(self.app.simulation_engines['b'], self.engine)
        self.old_tunnel.__aexit__.assert_not_awaited()
        self.app.create_engine_for_device.assert_not_awaited()
        self.assertEqual(self.events.await_count, 0)

    async def test_unverified_usb_never_replaces_existing_wifi(self):
        self.new.connection_type = 'Network'
        with patch.object(self.dm, '_open_connection', AsyncMock(return_value=self.new)):
            await self._poll_once()
        self.assertIs(self.dm._connections['b'], self.old)
        self.new.tunnel_context.__aexit__.assert_awaited_once()
        self.assertEqual(self.events.await_count, 0)

    async def test_active_simulation_is_not_replaced_or_cleared(self):
        self.engine.state = SimulationState.LOOPING
        self.engine.current_position = Coordinate(lat=25, lng=121)
        self.old_service._active = True
        with patch.object(self.dm, '_open_connection', AsyncMock()) as open_usb:
            await self._poll_once()
        open_usb.assert_not_awaited()
        self.assertIs(self.dm._connections['b'], self.old)
        self.assertIs(self.app.simulation_engines['b'], self.engine)
        self.old_tunnel.__aexit__.assert_not_awaited()
        self.assertEqual(self.events.await_count, 0)

    async def test_restored_but_retained_last_coordinate_is_not_replaced(self):
        self.engine.current_position = Coordinate(lat=25, lng=121)
        with patch.object(self.dm, '_open_connection', AsyncMock()) as open_usb:
            await self._poll_once()
        open_usb.assert_not_awaited()
        self.assertIs(self.app.simulation_engines['b'], self.engine)

    async def test_opted_out_device_cannot_be_upgraded_in_background(self):
        self.app._auto_connect_udids = []
        with patch.object(self.dm, '_open_connection', AsyncMock()) as open_usb:
            await self._poll_once()
        open_usb.assert_not_awaited()
        self.assertIs(self.dm._connections['b'], self.old)

    async def test_manual_disconnect_prevents_upgrade_even_if_opted_in(self):
        self.dm.mark_user_disconnected('B')
        with patch.object(self.dm, '_open_connection', AsyncMock()) as open_usb:
            await self._poll_once()
        open_usb.assert_not_awaited()
        self.assertIs(self.dm._connections['b'], self.old)

    async def test_engine_rebuild_failure_rolls_back_network_and_closes_usb(self):
        self.app.create_engine_for_device.side_effect = RuntimeError('rebuild failed')
        with patch.object(self.dm, '_open_connection', AsyncMock(return_value=self.new)), patch.object(
            self.dm, '_create_dvt_location_service', AsyncMock(return_value=self.new_service)
        ):
            await self._poll_once()
        self.assertIs(self.dm._connections['b'], self.old)
        self.assertIs(self.app.simulation_engines['b'], self.engine)
        self.new.tunnel_context.__aexit__.assert_awaited_once()
        self.old_tunnel.__aexit__.assert_not_awaited()
        self.assertEqual(self.events.await_count, 0)

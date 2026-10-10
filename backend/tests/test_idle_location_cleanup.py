"""Regression tests: idle disconnect must not send GPS writes to an iPhone.

All device transports and location instruments here are mocks. No physical
phone or developer image is accessed by this test suite.
"""
import unittest
from unittest.mock import AsyncMock, patch

from core.device_manager import DeviceManager, _ActiveConnection
from services.location_service import DvtLocationService, LegacyLocationService


class IdleLocationCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_idle_dvt_disconnect_never_initializes_or_clears_instrument(self):
        provider = AsyncMock()
        service = DvtLocationService(provider)
        dm = DeviceManager()
        dm._connections['device-b'] = _ActiveConnection(
            udid='device-b', lockdown=AsyncMock(), ios_version='27.0.1',
            connection_type='Network', location_service=service,
        )
        with patch('services.location_service.LocationSimulation') as instrument:
            await dm.disconnect('device-b')
        instrument.assert_not_called()
        provider.assert_not_awaited()
        self.assertFalse(service._active)
        self.assertEqual(dm.connected_udids, [])

    async def test_idle_dvt_disconnect_does_not_clear_cached_instrument(self):
        service = DvtLocationService(AsyncMock())
        cached_instrument = AsyncMock()
        service._location_sim = cached_instrument
        dm = DeviceManager()
        dm._connections['device-b'] = _ActiveConnection(
            udid='device-b', lockdown=AsyncMock(), ios_version='27.0.1',
            location_service=service,
        )
        await dm.disconnect('device-b')
        cached_instrument.clear.assert_not_awaited()

    async def test_idle_legacy_disconnect_does_not_send_clear(self):
        lockdown = AsyncMock()
        service = LegacyLocationService(lockdown)
        cached_service = AsyncMock()
        service._service = cached_service
        dm = DeviceManager()
        dm._connections['legacy'] = _ActiveConnection(
            udid='legacy', lockdown=lockdown, ios_version='16.0',
            location_service=service,
        )
        await dm.disconnect('legacy')
        cached_service.clear.assert_not_awaited()

    async def test_active_dvt_disconnect_still_clears_only_its_own_simulation(self):
        service = DvtLocationService(AsyncMock())
        simulated_instrument = AsyncMock()
        service._location_sim = simulated_instrument
        service._active = True
        dm = DeviceManager()
        dm._connections['device-b'] = _ActiveConnection(
            udid='device-b', lockdown=AsyncMock(), ios_version='27.0.1',
            location_service=service,
        )
        await dm.disconnect('device-b')
        simulated_instrument.clear.assert_awaited_once_with()
        self.assertFalse(service._active)

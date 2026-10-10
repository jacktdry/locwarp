"""Native Wi-Fi recovery uses owned mock transports, never a physical phone."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import main
from core.device_manager import DeviceManager, _ActiveConnection
from core.simulation_engine import SimulationEngine
from models.schemas import Coordinate, SimulationState
from services.location_service import DeviceLostError


class NativeRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dm = DeviceManager()
        self.state = main.AppState.__new__(main.AppState)
        self.state.device_manager = self.dm
        self.state.simulation_engines = {}
        self.state._primary_udid = 'a'
        self.state._last_position = None
        self.old = {}
        self.handles = []
        self.providers = []
        self.instruments = []
        self.events = AsyncMock()
        self.resume = AsyncMock()
        self.sync = AsyncMock()
        patches = [
            patch('core.device_manager.sys.platform', 'darwin'),
            patch.object(main, 'app_state', self.state),
            patch('api.websocket.broadcast', self.events),
            patch.object(self.dm, '_ensure_personalized_ddi_mounted', AsyncMock()),
            patch('pymobiledevice3.remote.native_tunnel.NativeRemotedTunnel', side_effect=self.new_handle),
            patch('pymobiledevice3.remote.rsd_tunnel.PreferredRsdTunnel', side_effect=AssertionError('USB prohibited')),
            patch('core.device_manager.CoreDeviceTunnelProxy.create', side_effect=AssertionError('kernel TUN prohibited')),
            patch('core.device_manager.DvtProvider', side_effect=self.new_provider),
            patch('services.location_service.LocationSimulation', side_effect=self.new_instrument),
            patch.object(SimulationEngine, 'resume_from_snapshot', self.resume),
            patch.object(main, '_auto_sync_new_device_to_primary', self.sync),
            patch('api.device._attempt_tunnel_restart', side_effect=AssertionError('Windows restart prohibited')),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        for udid in ('a', 'b'):
            context, rsd, service = AsyncMock(), AsyncMock(), AsyncMock()
            conn = _ActiveConnection(udid, rsd, '18.0', connection_type='Network',
                                     name=udid, rsd=rsd, tunnel_context=context,
                                     location_service=service, dvt_provider=AsyncMock())
            self.old[udid] = conn
            self.dm._connections[udid] = conn
            await self.state.create_engine_for_device(udid)
        self.original_engines = dict(self.state.simulation_engines)

    async def asyncTearDown(self):
        for engine in self.state.simulation_engines.values():
            for name in ('_native_resume_task', '_native_follow_task'):
                task = getattr(engine, name, None)
                if task is not None and not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        await self.dm.disconnect_all()

    def new_handle(self, serial):
        handle = AsyncMock()
        self.handles.append((serial, handle))
        return handle

    def new_provider(self, lockdown):
        provider = AsyncMock()
        self.providers.append(provider)
        return provider

    def new_instrument(self, provider):
        instrument = AsyncMock()
        self.instruments.append(instrument)
        return instrument

    def route(self, udid):
        engine = self.state.simulation_engines[udid]
        engine.state = SimulationState.LOOPING
        engine.current_position = Coordinate(lat=25.1, lng=121.2)
        engine._last_sim_kind = 'start_loop'
        engine._last_sim_args = {'waypoints': [Coordinate(lat=25, lng=121)]}
        engine._user_waypoint_next = 3
        engine.lap_count = 4
        engine.distance_traveled = 123
        return engine.capture_resumable_snapshot()

    async def test_primary_recovery_resumes_snapshot_and_preserves_sibling(self):
        snapshot = self.route('a')
        sibling, sibling_engine = self.old['b'], self.original_engines['b']
        # The registry must not even be read for native connections.
        class ForbiddenRegistry(dict):
            def get(self, *args):
                raise AssertionError('native recovery read Windows registry')
        with patch('api.device._tunnels', ForbiddenRegistry()):
            self.assertTrue(await self.dm.full_reconnect('a'))
        await self.state.simulation_engines['a']._native_resume_task
        self.resume.assert_awaited_once_with(snapshot)
        self.sync.assert_not_awaited()
        self.assertEqual(self.state._primary_udid, 'a')
        self.assertIs(self.dm._connections['b'], sibling)
        self.assertIs(self.state.simulation_engines['b'], sibling_engine)
        sibling.tunnel_context.__aexit__.assert_not_awaited()
        self.old['a'].tunnel_context.__aexit__.assert_awaited_once()
        self.assertIsNot(self.state.simulation_engines['a'], self.original_engines['a'])
        self.instruments[0].connect.assert_awaited_once()
        self.instruments[0].set.assert_not_awaited()
        self.assertEqual([call.args[0] for call in self.events.await_args_list],
                         ['tunnel_degraded', 'tunnel_recovered', 'device_connected'])
        self.assertTrue(all(call.args[1]['udid'] == 'a' for call in self.events.await_args_list))

    async def test_follower_recovery_reattaches_to_surviving_primary(self):
        self.route('a')
        self.assertTrue(await self.dm.full_reconnect('b'))
        await self.state.simulation_engines['b']._native_resume_task
        self.sync.assert_awaited_once_with('b')
        self.resume.assert_not_awaited()
        self.assertIs(self.state.simulation_engines['a'], self.original_engines['a'])
        self.old['a'].tunnel_context.__aexit__.assert_not_awaited()

    async def test_manual_disconnect_during_handshake_prevents_publication(self):
        from api.device import disconnect_device
        entered, release = asyncio.Event(), asyncio.Event()
        def handle(serial):
            context = self.new_handle(serial)
            async def enter():
                entered.set()
                await release.wait()
                return context.__aenter__.return_value
            context.__aenter__.side_effect = enter
            return context
        with patch('pymobiledevice3.remote.native_tunnel.NativeRemotedTunnel', side_effect=handle):
            recovery = asyncio.create_task(self.dm.full_reconnect('a'))
            await entered.wait()
            disconnect = asyncio.create_task(disconnect_device('a'))
            await asyncio.sleep(0)
            self.assertFalse(self.dm.auto_connect_allowed('a'))
            await asyncio.wait_for(disconnect, 1)
            self.assertFalse(await recovery)
            self.assertFalse(release.is_set())
        self.assertNotIn('a', self.dm._connections)
        self.assertNotIn('a', self.state.simulation_engines)
        self.handles[0][1].__aexit__.assert_awaited_once()
        self.resume.assert_not_awaited()
        self.assertNotIn('tunnel_recovered', [call.args[0] for call in self.events.await_args_list])
        self.assertIs(self.dm._connections['b'], self.old['b'])

    async def test_exhaustion_closes_every_attempt_and_removes_phantom_engine(self):
        async def no_delay(_):
            pass
        with patch('core.device_manager.DvtProvider', side_effect=ConnectionError('dead DVT')), patch(
            'asyncio.sleep', no_delay
        ):
            self.assertFalse(await self.dm.full_reconnect('a'))
        self.assertEqual(len(self.handles), 3)
        for _, context in self.handles:
            context.__aexit__.assert_awaited_once()
        self.assertEqual(self.dm.connected_udids, ['b'])
        self.assertEqual(list(self.state.simulation_engines), ['b'])
        self.assertFalse(await self.dm.full_reconnect('a'))
        self.assertEqual(len(self.handles), 3)
        self.assertEqual(self.state._primary_udid, 'b')
        lost = [c for c in self.events.await_args_list if c.args[0] == 'device_disconnected']
        self.assertEqual(lost[0].args[1]['udids'], ['a'])
        self.assertIs(self.dm._connections['b'], self.old['b'])

    async def test_dvt_only_transient_recovery_does_not_replace_native_tunnel(self):
        class ForbiddenRegistry(dict):
            def get(self, *args):
                raise AssertionError('native DVT recovery read Windows registry')
        with patch('api.device._tunnels', ForbiddenRegistry()):
            provider = await self.dm.get_fresh_dvt_provider('a')
        self.assertIs(provider, self.providers[0])
        self.assertEqual(self.handles, [])
        self.assertIs(self.dm._connections['a'], self.old['a'])
        self.old['a'].tunnel_context.__aexit__.assert_not_awaited()

    async def test_dvt_light_retries_are_bounded_and_failed_providers_closed(self):
        def failed_provider(lockdown):
            provider = self.new_provider(lockdown)
            provider.__aenter__.side_effect = ConnectionError('dead DVT')
            return provider
        async def no_delay(_):
            pass
        with patch('core.device_manager.DvtProvider', side_effect=failed_provider), patch('asyncio.sleep', no_delay):
            with self.assertRaises(DeviceLostError):
                await self.dm.get_fresh_dvt_provider('a')
        self.assertEqual(len(self.providers), 3)
        for provider in self.providers:
            provider.__aexit__.assert_awaited_once()
        self.old['a'].tunnel_context.__aexit__.assert_not_awaited()

    async def test_two_requests_share_one_native_handshake(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.dm._connect_tunnel
        async def gated(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)
        with patch.object(self.dm, '_connect_tunnel', gated):
            first = asyncio.create_task(self.dm.full_reconnect('a'))
            await entered.wait()
            second = asyncio.create_task(self.dm.full_reconnect('a'))
            await asyncio.sleep(0)
            release.set()
            self.assertEqual(await asyncio.gather(first, second), [True, True])
        self.assertEqual(len(self.handles), 1)

    async def test_background_position_failure_recovers_with_new_service(self):
        engine = self.original_engines['a']
        engine.location_service.set.side_effect = DeviceLostError('dead native tunnel')
        await engine._set_position(25.2, 121.3)
        replacement = self.state.simulation_engines['a']
        self.assertIsNot(replacement, engine)
        self.assertEqual(replacement.current_position, Coordinate(lat=25.2, lng=121.3))
        self.instruments[0].set.assert_awaited_once_with(25.2, 121.3)
        self.old['b'].tunnel_context.__aexit__.assert_not_awaited()

    async def test_engine_build_failure_rolls_back_native_connection(self):
        async def no_delay(_):
            pass
        with patch.object(self.state, 'create_engine_for_device', AsyncMock(side_effect=RuntimeError('engine failed'))), patch(
            'asyncio.sleep', no_delay
        ):
            self.assertFalse(await self.dm.full_reconnect('a'))
        self.assertNotIn('a', self.dm._connections)
        self.assertNotIn('a', self.state.simulation_engines)
        for _, context in self.handles:
            context.__aexit__.assert_awaited_once()


    async def test_route_requesting_recovery_is_not_cancelled_by_its_own_cleanup(self):
        engine = self.original_engines['a']
        self.route('a')
        engine.location_service.set.side_effect = DeviceLostError('route DVT failed')
        task = asyncio.create_task(engine._set_position(25.3, 121.4))
        engine._active_task = task
        await asyncio.wait_for(task, 1)
        self.assertFalse(task.cancelled())
        self.assertTrue(engine._stop_event.is_set())
        await self.state.simulation_engines['a']._native_resume_task
        self.resume.assert_awaited_once()
        self.old['b'].tunnel_context.__aexit__.assert_not_awaited()

    async def test_failed_position_retry_cleans_replacement_and_keeps_sibling(self):
        engine = self.original_engines['a']
        engine.location_service.set.side_effect = DeviceLostError('old native failed')
        def failed_instrument(provider):
            instrument = self.new_instrument(provider)
            instrument.set.side_effect = RuntimeError('invalid instrument')
            return instrument
        # Model a service-level terminal failure, rather than an unpaired phone.
        with patch('services.location_service.LocationSimulation', side_effect=failed_instrument):
            async def failed_set(lat, lng):
                raise DeviceLostError('replacement service failed')
            original = self.dm._create_dvt_location_service
            async def create(*args, **kwargs):
                service = await original(*args, **kwargs)
                service.set = failed_set
                return service
            with patch.object(self.dm, '_create_dvt_location_service', create):
                with self.assertRaises(DeviceLostError):
                    await engine._set_position(25.2, 121.3)
        self.assertNotIn('a', self.dm._connections)
        self.assertNotIn('a', self.state.simulation_engines)
        self.assertIs(self.dm._connections['b'], self.old['b'])

    async def test_other_wifi_device_can_recover_while_first_handshake_is_blocked(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.dm._connect_tunnel
        async def gated(udid, *args, **kwargs):
            if udid == 'a':
                entered.set()
                await release.wait()
            return await original(udid, *args, **kwargs)
        with patch.object(self.dm, '_connect_tunnel', gated):
            first = asyncio.create_task(self.dm.full_reconnect('a'))
            await entered.wait()
            try:
                self.assertTrue(await asyncio.wait_for(self.dm.full_reconnect('b'), 1))
                self.assertFalse(first.done())
            finally:
                release.set()
                self.assertTrue(await first)

    async def test_manual_disconnect_during_dvt_probe_does_not_publish_provider(self):
        from api.device import disconnect_device
        entered, release = asyncio.Event(), asyncio.Event()
        provider = self.new_provider(self.old['a'].lockdown)
        async def enter():
            entered.set()
            await release.wait()
        provider.__aenter__.side_effect = enter
        with patch('core.device_manager.DvtProvider', return_value=provider):
            probe = asyncio.create_task(self.dm.get_fresh_dvt_provider('a'))
            await entered.wait()
            await disconnect_device('a')
            release.set()
            with self.assertRaises(DeviceLostError):
                await probe
        provider.__aexit__.assert_awaited_once()
        self.assertNotIn('a', self.dm._connections)
        self.assertNotIn('a', self.state.simulation_engines)

    async def test_cancelled_recovery_rolls_back_unpublished_dvt_and_engine(self):
        entered = asyncio.Event()
        original = self.dm._create_dvt_location_service
        async def blocked(conn, **kwargs):
            await original(conn, **kwargs)
            entered.set()
            await asyncio.Event().wait()
        with patch.object(self.dm, '_create_dvt_location_service', blocked):
            caller = asyncio.create_task(self.dm.full_reconnect('a'))
            await entered.wait()
            self.dm._native_recoveries['a'].cancel()
            with self.assertRaises(asyncio.CancelledError):
                await caller
        self.assertNotIn('a', self.dm._connections)
        self.assertNotIn('a', self.state.simulation_engines)
        self.handles[0][1].__aexit__.assert_awaited_once()
        self.providers[0].__aexit__.assert_awaited_once()
        self.assertIs(self.dm._connections['b'], self.old['b'])


    async def test_idle_native_devices_receive_no_periodic_location_probe(self):
        self.state._wifi_keepalive_enabled = True
        for engine in self.state.simulation_engines.values():
            engine.current_position = Coordinate(lat=25.1, lng=121.2)
        ticks = 0
        async def sleep(_):
            nonlocal ticks
            ticks += 1
            if ticks > 1:
                raise asyncio.CancelledError
        with patch('asyncio.sleep', sleep):
            with self.assertRaises(asyncio.CancelledError):
                await main._wifi_tunnel_keepalive()
        for conn in self.old.values():
            conn.location_service.set.assert_not_awaited()

    async def test_native_manual_disconnect_never_reads_runner_registry(self):
        from api.device import disconnect_device
        class ForbiddenRegistry(dict):
            def __contains__(self, key):
                raise AssertionError('native disconnect read Windows registry')
        with patch('api.device._tunnels', ForbiddenRegistry()):
            await disconnect_device('a')
        self.assertEqual(self.dm.connected_udids, ['b'])
        self.assertFalse(self.dm.auto_connect_allowed('a'))

    async def test_disconnect_all_invalidates_pending_native_recovery(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.dm._connect_tunnel
        async def blocked(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)
        with patch.object(self.dm, '_connect_tunnel', blocked):
            caller = asyncio.create_task(self.dm.full_reconnect('a'))
            await entered.wait()
            teardown = asyncio.create_task(self.dm.disconnect_all())
            await asyncio.sleep(0)
            await asyncio.wait_for(teardown, 1)
            self.assertFalse(await caller)
        self.assertEqual(self.dm.connected_udids, [])
        self.assertNotIn('a', self.state.simulation_engines)
        self.assertEqual(self.handles, [])

    async def test_route_replay_is_only_writer_after_failed_position(self):
        engine = self.original_engines['a']
        snapshot = self.route('a')
        engine.location_service.set.side_effect = DeviceLostError('route failed')
        entered, release = asyncio.Event(), asyncio.Event()
        async def resume(replacement, snap):
            self.assertEqual(snap, snapshot)
            entered.set()
            await replacement.location_service.set(*snap['current_pos'])
            await release.wait()
        with patch.object(SimulationEngine, 'resume_from_snapshot', resume):
            await engine._set_position(26.0, 122.0)
            await entered.wait()
            replacement = self.state.simulation_engines['a']
            self.assertEqual(replacement.current_position, Coordinate(lat=25.1, lng=121.2))
            self.instruments[0].set.assert_awaited_once_with(25.1, 121.2)
            release.set()
            await replacement._native_resume_task

    async def test_connect_and_disconnect_case_variant_preserve_single_engine(self):
        from api.device import connect_device, disconnect_device
        engine = self.original_engines['a']
        with patch.object(self.dm, 'discover_devices', AsyncMock(return_value=[])), patch.object(
            self.dm, '_open_connection', AsyncMock(side_effect=AssertionError('duplicate connection'))
        ):
            result = await connect_device('A')
        self.assertEqual(result['udid'], 'a')
        self.assertIs(self.state.simulation_engines['a'], engine)
        self.assertNotIn('A', self.state.simulation_engines)
        self.assertIsNone(await self.dm.connect('A'))
        self.assertIs(await self.dm.get_location_service('A'), self.old['a'].location_service)
        await disconnect_device('A')
        self.assertNotIn('a', self.state.simulation_engines)
        self.assertNotIn('a', self.dm._connections)
        self.assertIs(self.dm._connections['b'], self.old['b'])

    async def test_repeated_cancellation_yields_and_shares_one_cleanup(self):
        conn = self.old['a']
        entered, release = asyncio.Event(), asyncio.Event()
        async def close(*args):
            entered.set()
            await release.wait()
        conn.tunnel_context.__aexit__.side_effect = close
        first = asyncio.create_task(self.dm._close_connection(conn))
        await entered.wait()
        second = asyncio.create_task(self.dm._close_connection(conn))
        # Every cancel must yield to the heartbeat while handles stay owned.
        for _ in range(5):
            first.cancel()
            await asyncio.sleep(0)
            self.assertFalse(first.done())
            self.assertFalse(conn._cleanup_task.cancelled())
        conn.tunnel_context.__aexit__.assert_awaited_once()
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await first
        await second
        await self.dm._close_connection(conn)
        conn.tunnel_context.__aexit__.assert_awaited_once()

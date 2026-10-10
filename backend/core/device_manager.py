"""
LocWarp Device Manager

Handles iOS device detection, connection lifecycle, tunnel establishment,
and location service creation.  Wraps pymobiledevice3 internals so the
rest of the application never touches low-level device APIs directly.

Supports both USB and WiFi connections.  ``list_devices()`` from usbmuxd
returns devices with ``connection_type`` of ``"USB"`` or ``"Network"``.
WiFi requires the device to be paired and on the same local network.

For iOS 17+, a TCP tunnel via CoreDeviceTunnelProxy is established first,
then a RemoteServiceDiscoveryService (RSD) is created over the tunnel to
access DVT services.  This requires administrator privileges on Windows.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from pymobiledevice3.lockdown import create_using_usbmux, create_using_tcp
from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService
from pymobiledevice3.remote.tunnel_service import CoreDeviceTunnelProxy
from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
from pymobiledevice3.services.simulate_location import DtSimulateLocation
from pymobiledevice3.usbmux import list_devices

from config import DEVICE_NAMES_FILE
from models.schemas import DeviceInfo
from services.json_safe import safe_load_json, safe_write_json
from services.location_service import (
    DeviceLostError,
    DvtLocationService,
    LegacyLocationService,
    LocationService,
)


class UnsupportedIosVersionError(RuntimeError):
    """Raised when a connecting device's iOS version is below the minimum
    supported by LocWarp (currently 16.0). Surfaces a structured error to
    the API layer so the frontend can show an actionable message rather
    than a stack trace."""

    MIN_VERSION = "16.0"

    def __init__(self, version: str) -> None:
        self.version = version
        super().__init__(f"iOS {version} is not supported (requires {self.MIN_VERSION}+)")

logger = logging.getLogger(__name__)


def _parse_ios_version(version_string: str) -> tuple[int, ...]:
    """Convert an iOS version string like '17.4.1' into a comparable tuple."""
    try:
        return tuple(int(p) for p in version_string.split("."))
    except (ValueError, AttributeError):
        logger.warning("Unable to parse iOS version '%s', assuming 0.0", version_string)
        return (0, 0)


def _load_device_name_cache() -> Dict[str, str]:
    """Load the persisted UDID → DeviceName map. Returns empty dict on any failure."""
    raw = safe_load_json(DEVICE_NAMES_FILE)
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if isinstance(v, str) and v}


def _remember_device_name(udid: str, name: str) -> None:
    """Persist a real DeviceName for *udid* if it isn't a generic fallback.

    The cache only stores user-set names. We deliberately skip the
    DeviceClass fallback ("iPhone") and "Unknown" so a once-known real
    name isn't overwritten by a later degraded read.
    """
    if not udid or not name:
        return
    if name in ("iPhone", "iPad", "iPod touch", "Unknown"):
        return
    cache = _load_device_name_cache()
    if cache.get(udid) == name:
        return
    cache[udid] = name
    safe_write_json(DEVICE_NAMES_FILE, cache)


@dataclass
class _ActiveConnection:
    """Internal bookkeeping for a single connected device."""
    udid: str
    lockdown: object  # LockdownClient or RemoteServiceDiscoveryService
    ios_version: str
    connection_type: str = "USB"  # "USB" or "Network"
    name: str = "iPhone"  # Cached DeviceName so discover_devices can surface
                          # WiFi-tunnel devices that no longer appear in usbmuxd
                          # after USB is unplugged (RemotePairing tunnel only).
    dvt_provider: Optional[DvtProvider] = None
    tunnel_proxy: Optional[CoreDeviceTunnelProxy] = None
    tunnel_context: object = None  # async context manager for the tunnel
    rsd: Optional[RemoteServiceDiscoveryService] = None
    location_service: Optional[LocationService] = None
    usbmux_lockdown: object = None  # Original lockdown client (for legacy fallback on iOS 17+)
    _cleanup_task: Optional[asyncio.Task] = None


class DeviceManager:
    """
    Manages the full lifecycle of iOS device connections.

    Usage::

        dm = DeviceManager()
        devices = await dm.discover_devices()
        await dm.connect(devices[0].udid)
        loc = await dm.get_location_service(devices[0].udid)
        await loc.set(37.7749, -122.4194)
        await dm.disconnect(devices[0].udid)
    """

    def __init__(self) -> None:
        self._connections: Dict[str, _ActiveConnection] = {}
        self._lock = asyncio.Lock()
        # Owned PreferredRsdTunnel context, including handshake-before-publish.
        # pymobiledevice3 11.26 permits only one process-wide userspace relay.
        self._mac_usb_userspace_context: object = None
        # Coordination keys are case-insensitive; published UDIDs retain their case.
        self._connection_locks: dict[str, asyncio.Lock] = {}
        self._disconnect_generations: dict[str, int] = {}
        self._user_disconnected: set[str] = set()
        self._connection_reservations: set[str] = set()
        self._native_recoveries: dict[str, asyncio.Task] = {}
        self._native_recovery_waiters: dict[str, set[asyncio.Task]] = {}

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    @staticmethod
    async def _mac_native_candidates() -> list[dict]:
        """Browse *paired* macOS Wi-Fi devices without opening a tunnel.

        Apple remotepairingd can retain a device record even while it is
        temporarily offline. A result is a candidate, never a successful
        connection; connecting must still prove reachability via native RSD.
        """
        if sys.platform != "darwin":
            return []
        try:
            from pymobiledevice3.remote.native_tunnel import browse_native_devices
            records = await asyncio.wait_for(browse_native_devices(timeout=2), timeout=6)
            # networkAdvertActive may become false when the screen sleeps,
            # even for a phone whose native RSD remains connectable. Do not
            # confuse this discovery hint with successful live connectivity.
            return [record for record in records
                    if record.get("udid")
                    and (record.get("authState") or {}).get("rawCase") == "authenticated"]
        except Exception:
            logger.warning("macOS native Wi-Fi discovery unavailable", exc_info=True)
            return []

    async def discover_devices(self) -> list[DeviceInfo]:
        """
        Scan for all iOS devices visible over USB and WiFi (usbmuxd).

        usbmuxd returns both USB-connected and WiFi-paired devices on
        the same network.  Each device carries a ``connection_type`` of
        ``"USB"`` or ``"Network"``.

        Returns a list of ``DeviceInfo`` objects with basic identification
        data.  This does **not** establish a persistent connection.
        """
        devices: list[DeviceInfo] = []
        seen_udids: set[str] = set()

        try:
            raw_devices = await list_devices()
        except Exception:
            logger.exception("Failed to list usbmux devices")
            raw_devices = []

        for raw in raw_devices:
            try:
                conn_type = getattr(raw, "connection_type", "USB")
                # If we already saw this device via USB, skip the Network duplicate
                if raw.serial in seen_udids:
                    # But upgrade to USB if this entry is USB (prefer USB info)
                    if conn_type == "USB":
                        for d in devices:
                            if d.udid == raw.serial:
                                d.connection_type = "USB"
                    continue
                seen_udids.add(raw.serial)

                lockdown = await create_using_usbmux(serial=raw.serial)
                all_values = lockdown.all_values
                # If device is already connected, report the active connection type
                active_conn = self._connections.get(raw.serial)
                if active_conn:
                    conn_type = active_conn.connection_type
                device_name = all_values.get("DeviceName", "Unknown")
                _remember_device_name(raw.serial, device_name)
                info = DeviceInfo(
                    udid=raw.serial,
                    name=device_name,
                    ios_version=all_values.get("ProductVersion", "0.0"),
                    connection_type=conn_type,
                )
                info.is_connected = raw.serial in self._connections
                # Query Developer Mode status (iOS 16+). Tolerate failure —
                # None means "unknown", frontend will hide the reveal button.
                try:
                    ver = _parse_ios_version(info.ios_version)
                    if ver >= (16, 0):
                        info.developer_mode_enabled = await lockdown.get_developer_mode_status()
                except Exception:
                    logger.debug("get_developer_mode_status failed for %s", raw.serial, exc_info=True)
                devices.append(info)
                logger.debug("Discovered device %s (%s) running iOS %s via %s (connected=%s)",
                             info.name, info.udid, info.ios_version, conn_type, info.is_connected)
            except Exception:
                logger.exception("Failed to query device %s", getattr(raw, "serial", "?"))

        # Surface devices that are in our connection table but did not get
        # added from usbmuxd above. Happens for the dual-device A-WiFi +
        # B-USB flow: A is paired via the in-process RemotePairing tunnel
        # (port 49152), NOT through usbmuxd's iTunes-WiFi-sync path, so
        # once A's USB cable is unplugged usbmuxd may stop listing A
        # entirely. Without this fallback `discover_devices()` would
        # return only B, and the frontend's listDevices refresh on B's
        # auto-connect broadcast would wipe A out of the device sidebar /
        # connectedDevices fanout, so the user would see A as if it had
        # been kicked. Compare against actually-added udids (not
        # `seen_udids` which is set early for raw-entry dedup) so a
        # failed lockdown query above doesn't suppress the fallback.
        added_udids = {d.udid for d in devices}
        for udid, conn in self._connections.items():
            if udid in added_udids:
                continue
            try:
                info = DeviceInfo(
                    udid=udid,
                    name=conn.name or "iPhone",
                    ios_version=conn.ios_version or "0.0",
                    connection_type=conn.connection_type or "Network",
                )
                info.is_connected = True
                devices.append(info)
                added_udids.add(udid)
                logger.debug(
                    "Discovered cached %s device %s (%s) iOS %s (no usbmux entry)",
                    conn.connection_type, info.name, udid, info.ios_version,
                )
            except Exception:
                logger.exception("Failed to surface cached connection for %s", udid)

        # USBmux can omit an iPhone even while Apple's own remotepairingd
        # can establish a no-root Wi-Fi RSD. Expose *paired candidates* here
        # so users can explicitly connect; no tunnel is opened during scan.
        if sys.platform == "darwin":
            native_records = await self._mac_native_candidates()
            for record in native_records:
                udid = record["udid"]
                if udid in added_udids:
                    continue
                active = self._connections.get(udid)
                # A stale Wi-Fi record is not proof the phone is online.
                # Its OS version is unknown until a real RSD connects.
                info = DeviceInfo(
                    udid=udid,
                    name=(active.name if active else record.get("name"))
                    or _load_device_name_cache().get(udid, "iPhone"),
                    ios_version=active.ios_version if active else "0.0",
                    connection_type=active.connection_type if active else "Network",
                    is_connected=active is not None,
                )
                devices.append(info)
                added_udids.add(udid)
        return devices

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def auto_connect_allowed(self, udid: str) -> bool:
        return udid.lower() not in self._user_disconnected

    def mark_user_disconnected(self, udid: str) -> None:
        """Persist session intent across USB polls, failures and unplug/replug."""
        key = udid.lower()
        self._user_disconnected.add(key)
        self._disconnect_generations[key] = self._disconnect_generations.get(key, 0) + 1

    def _connection_lock(self, udid: str) -> asyncio.Lock:
        return self._connection_locks.setdefault(udid.lower(), asyncio.Lock())

    def canonical_udid(self, udid: str) -> str:
        key = udid.lower()
        return next((u for u in self._connections if u.lower() == key), udid)

    async def connect(self, udid: str, *, user_initiated: bool = False,
                      native_record: dict | None = None, approval_check=None,
                      prepare_connection=None) -> _ActiveConnection | None:
        """Serialize one device's handshake/publication without blocking siblings.

        A disconnect invalidates every earlier request, including lock waiters.
        Only explicit user connect clears the session's auto-reconnect suppression.
        """
        key = udid.lower()
        if user_initiated:
            self._user_disconnected.discard(key)
        generation = self._disconnect_generations.get(key, 0)
        async with self._connection_lock(udid):
            def check_intent():
                if (generation != self._disconnect_generations.get(key, 0)
                        or not self.auto_connect_allowed(udid)
                        or (approval_check is not None and not approval_check())):
                    raise ConnectionAbortedError(f"Connection to {udid} was disconnected")

            check_intent()
            if any(u.lower() == key for u in self._connections):
                return
            if self.connection_count() >= 3:
                raise RuntimeError("Maximum of 3 connected devices reached")
            self._connection_reservations.add(key)
            conn = None
            try:
                conn = await self._open_connection(udid, native_record=native_record,
                                                   require_native_record=approval_check is not None)
                if prepare_connection is not None:
                    await prepare_connection(conn)
                check_intent()
                async with self._lock:
                    check_intent()
                    self._connections[udid] = conn
                return conn
            except BaseException:
                if conn is not None:
                    await self._close_connection(conn)
                raise
            finally:
                self._connection_reservations.discard(key)

    async def _open_connection(self, udid: str, *, native_record: dict | None = None,
                               require_native_record: bool = False) -> _ActiveConnection:
        conn = None
        lockdown = None
        try:
            # Detect connection type from usbmux device list. macOS can also
            # connect an Apple-native paired Wi-Fi record missing from USBmux.
            connection_type = "USB"
            in_usbmux = False
            try:
                raw_devices = await list_devices()
                for raw in raw_devices:
                    if raw.serial.lower() == udid.lower():
                        in_usbmux = True
                        connection_type = getattr(raw, "connection_type", "USB")
                        # Prefer USB if device shows up as both
                        if connection_type == "USB":
                            break
            except Exception:
                logger.debug("Could not determine connection type for %s", udid)

            if sys.platform == "darwin" and (not in_usbmux or (native_record is not None and connection_type != "USB")):
                if require_native_record and (native_record is None or (
                        native_record.get("networkAdvertActive") is not True
                        and (not in_usbmux or connection_type != "Network"))):
                    raise ConnectionAbortedError("No reachable approved native Wi-Fi record")
                records = [native_record] if native_record is not None else await self._mac_native_candidates()
                selected = next((r for r in records if r["udid"].lower() == udid.lower()
                                 and (native_record is None or (r.get("authState") or {}).get("rawCase") == "authenticated")), None)
                if selected is None:
                    raise RuntimeError("找不到已配對的 macOS Wi-Fi iPhone。請解鎖手機、確認同一網路後重新掃描。")
                conn = await self._connect_tunnel(udid, None, "0.0", "Network")
                # The OS version only becomes authoritative after the RSD
                # handshake. Reject unsupported devices and release assertions.
                rsd = conn.rsd
                props = (getattr(rsd, "peer_info", None) or {}).get("Properties", {})
                values = getattr(rsd, "all_values", None) or {}
                version = (getattr(rsd, "product_version", None)
                           or values.get("ProductVersion")
                           or props.get("OSVersion") or "0.0")
                if _parse_ios_version(version) < (17, 0):
                    raise UnsupportedIosVersionError(version)
                name = values.get("DeviceName") or selected.get("name") or "iPhone"
                _remember_device_name(udid, name)
                conn.ios_version = version
                conn.name = name
                conn.connection_type = "Network"
                logger.info("Connected to %s (iOS %s) via macOS native Wi-Fi", udid, version)
                return conn

            logger.info("Connecting to %s via %s", udid, connection_type)

            # Create a fresh lockdown client to read the iOS version.
            try:
                lockdown = await create_using_usbmux(serial=udid)
            except Exception:
                logger.exception("Cannot create lockdown client for %s via %s", udid, connection_type)
                raise

            ios_version_str: str = lockdown.all_values.get("ProductVersion", "0.0")
            device_name: str = lockdown.all_values.get("DeviceName", "iPhone")
            _remember_device_name(udid, device_name)
            ver = _parse_ios_version(ios_version_str)

            if ver < (16, 0):
                logger.warning(
                    "Refusing connect: %s reports iOS %s, below minimum %s",
                    udid, ios_version_str, UnsupportedIosVersionError.MIN_VERSION,
                )
                raise UnsupportedIosVersionError(ios_version_str)

            if ver >= (17, 0):
                conn = await self._connect_tunnel(udid, lockdown, ios_version_str, connection_type)
            else:
                conn = self._connect_legacy(udid, lockdown, ios_version_str)
            conn.connection_type = connection_type
            conn.name = device_name

            logger.info("Connected to %s (iOS %s) via %s", udid, ios_version_str, connection_type)
            return conn
        except BaseException:
            if conn is not None:
                await self._close_connection(conn)
            elif lockdown is not None:
                await self._close_connection(_ActiveConnection(udid, lockdown, "0.0"))
            raise

    # -- iOS 17+ via CoreDeviceTunnelProxy ---------------------------------

    async def _connect_tunnel(
        self, udid: str, lockdown, ios_version: str, connection_type: str = "USB"
    ) -> _ActiveConnection:
        """Use an owned RSD tunnel appropriate for both OS and transport."""
        logger.debug("Establishing tunnel for %s (iOS %s, %s)", udid, ios_version, connection_type)

        proxy = tunnel_ctx = rsd = None
        second_usb_native = False
        try:
            if sys.platform == "darwin":
                if connection_type == "Network":
                    # The USB userspace relay can spin in uvloop/UDP after the
                    # cable is removed. For an already-paired Wi-Fi iPhone,
                    # borrow Apple's kernel-routable tunnel via remotepairingd.
                    # This uses no root and holds the assertion until disconnect.
                    from pymobiledevice3.remote.native_tunnel import NativeRemotedTunnel
                    tunnel_ctx = NativeRemotedTunnel(serial=udid)
                else:
                    # Prefer the tested userspace path for the first USB.
                    # Reserve before awaiting: two concurrent USB handshakes
                    # must not both try the process-global userspace singleton.
                    second_usb_native = self._mac_usb_userspace_context is not None or any(
                        conn.connection_type == "USB" and conn.tunnel_context is not None
                        and type(getattr(conn.tunnel_context, "_handle", None)).__name__ == "UserspaceRsdTunnel"
                        for conn in self._connections.values()
                    )
                    if second_usb_native:
                        # Preferred(prefer_native=True) falls back to userspace
                        # on native failure, which is unsafe while occupied.
                        from pymobiledevice3.remote.native_tunnel import NativeRemotedTunnel
                        tunnel_ctx = NativeRemotedTunnel(serial=udid)
                    else:
                        from pymobiledevice3.remote.rsd_tunnel import PreferredRsdTunnel
                        tunnel_ctx = PreferredRsdTunnel(serial=udid, autopair=False)
                        self._mac_usb_userspace_context = tunnel_ctx
                if second_usb_native:
                    rsd = await asyncio.wait_for(tunnel_ctx.__aenter__(), timeout=10)
                else:
                    rsd = await tunnel_ctx.__aenter__()
                # Preferred may itself choose native (e.g. iOS 17.0-17.3).
                # Its owned concrete handle is authoritative for this version.
                if (self._mac_usb_userspace_context is tunnel_ctx
                        and type(getattr(tunnel_ctx, "_handle", None)).__name__ == "NativeRemotedTunnel"):
                    self._mac_usb_userspace_context = None
                return _ActiveConnection(
                    udid=udid,
                    lockdown=rsd,
                    ios_version=ios_version,
                    tunnel_context=tunnel_ctx,
                    rsd=rsd,
                    usbmux_lockdown=lockdown,
                )
            proxy = await CoreDeviceTunnelProxy.create(lockdown)
            tunnel_ctx = proxy.start_tcp_tunnel()
            tunnel_result = await tunnel_ctx.__aenter__()

            logger.info("Tunnel established for %s: %s:%s",
                        udid, tunnel_result.address, tunnel_result.port)

            # Create RSD over the tunnel
            rsd = RemoteServiceDiscoveryService((tunnel_result.address, tunnel_result.port))
            await rsd.connect()
            logger.info("RSD connected for %s", udid)

            return _ActiveConnection(
                udid=udid,
                lockdown=rsd,
                ios_version=ios_version,
                tunnel_proxy=proxy,
                tunnel_context=tunnel_ctx,
                rsd=rsd,
                usbmux_lockdown=lockdown,
            )
        except BaseException as exc:
            await self._close_connection(_ActiveConnection(
                udid=udid, lockdown=None, ios_version=ios_version,
                tunnel_proxy=proxy, tunnel_context=tunnel_ctx, rsd=rsd,
            ))
            if not isinstance(exc, Exception):
                raise
            if sys.platform == "darwin":
                logger.exception("macOS %s RSD tunnel failed for %s", connection_type, udid)
                if connection_type == "Network":
                    raise RuntimeError(
                        "macOS Wi-Fi 通道無法建立。請確認手機與 Mac 位於同一個 Wi-Fi、"
                        "iPhone 已解鎖，且已透過 Finder / Xcode 完成配對。"
                        "若有 VPN、HomiPlay 等網路軟體，請檢查其網路設定。"
                        " / macOS Wi-Fi native tunnel failed: verify pairing, local network, "
                        "device unlock, and VPN routing."
                    ) from None
                if second_usb_native:
                    raise RuntimeError(
                        "第二台 USB 裝置的 macOS 原生通道無法建立。第一台連線已保留。"
                        "請解鎖手機，在 Finder 完成配對並啟用 Wi-Fi 顯示，確認同一網路後重試；"
                        "不需要管理員權限。 / macOS second USB native tunnel failed: "
                        "first connection retained; unlock, pair in Finder, enable Wi-Fi and retry."
                    ) from None
                raise RuntimeError(
                    "macOS USB 通道無法建立。請解鎖並信任 Mac、啟用開發者模式，"
                    "確認 DDI 已掛載並使用 pymobiledevice3 11.26.0 以上版本。"
                    " / macOS USB tunnel failed: check USB trust, Developer Mode, DDI, "
                    "and pymobiledevice3 >=11.26.0."
                ) from None
            logger.exception(
                "TCP tunnel failed for %s (iOS %s). "
                "Ensure you are running as administrator.",
                udid, ios_version,
            )
            raise RuntimeError(
                f"無法建立裝置通道 (iOS {ios_version})。"
                f"請以系統管理員身份執行 LocWarp。"
            )

    # iOS < 17 path removed in v0.1.49 — see UnsupportedIosVersionError.

    def _connect_legacy(
        self, udid: str, lockdown, ios_version: str
    ) -> _ActiveConnection:
        """Direct usbmux lockdown connection for iOS 16.x devices."""
        logger.info("Using legacy lockdown connection for %s (iOS %s)", udid, ios_version)
        return _ActiveConnection(
            udid=udid,
            lockdown=lockdown,
            ios_version=ios_version,
            usbmux_lockdown=lockdown,
        )

    # ------------------------------------------------------------------
    # Disconnection
    # ------------------------------------------------------------------

    async def disconnect(self, udid: str) -> None:
        """Tear down the connection and clean up resources for *udid*."""
        key = udid.lower()
        self._disconnect_generations[key] = self._disconnect_generations.get(key, 0) + 1
        recovery = self._native_recoveries.get(key)
        if recovery is not None and recovery is not asyncio.current_task() and not recovery.done():
            recovery.cancel()
        async with self._connection_lock(udid):
            async with self._lock:
                stored_udid = next((u for u in self._connections if u.lower() == key), udid)
                conn = self._connections.pop(stored_udid, None)
            if conn is not None:
                await self._close_connection(conn)

    @staticmethod
    async def _close_lockdown(lockdown, udid: str) -> None:
        try:
            await lockdown.close()
        except Exception:
            logger.exception("Error closing lockdown for %s", udid)

    async def _close_connection(self, conn: _ActiveConnection) -> None:
        # Finish releasing owned handles even if the caller is cancelled again.
        if conn._cleanup_task is None:
            conn._cleanup_task = asyncio.create_task(self._close_connection_handles(conn))
        cleanup = conn._cleanup_task
        cancelled = False
        while not cleanup.done():
            try:
                # wait always suspends and never forwards caller cancellation
                # to the single owned cleanup task.
                await asyncio.wait({cleanup})
            except asyncio.CancelledError:
                cancelled = True
        cleanup.result()
        if cancelled:
            raise asyncio.CancelledError

    async def _close_connection_handles(self, conn: _ActiveConnection) -> None:
        udid = conn.udid
        # Clear any active location simulation first.
        if conn.location_service is not None:
            try:
                await conn.location_service.clear()
            except Exception:
                logger.exception("Error clearing location on disconnect for %s", udid)

        # Shut down the DVT provider if it was opened.
        if conn.dvt_provider is not None:
            try:
                await conn.dvt_provider.__aexit__(None, None, None)
            except Exception:
                logger.exception("Error closing DvtProvider for %s", udid)

        # Close RSD.
        if conn.rsd is not None and (conn.tunnel_context is None or conn.tunnel_proxy is not None):
            try:
                await conn.rsd.close()
            except Exception:
                logger.exception("Error closing RSD for %s", udid)

        # Close tunnel context.
        if conn.tunnel_context is not None:
            try:
                await conn.tunnel_context.__aexit__(None, None, None)
                if self._mac_usb_userspace_context is conn.tunnel_context:
                    self._mac_usb_userspace_context = None
            except Exception:
                logger.exception("Error closing tunnel for %s", udid)

        # Close tunnel proxy.
        if conn.tunnel_proxy is not None:
            try:
                await conn.tunnel_proxy.close()
            except Exception:
                logger.exception("Error closing tunnel proxy for %s", udid)

        # macOS contexts own their RSD; kernel proxies have a separate RSD.
        lockdown = conn.usbmux_lockdown
        if lockdown is None and conn.rsd is None:
            lockdown = conn.lockdown
        if lockdown is not None:
            await self._close_lockdown(lockdown, udid)
        logger.info("Disconnected device %s", udid)

    # ------------------------------------------------------------------
    # Location service
    # ------------------------------------------------------------------

    async def get_location_service(self, udid: str) -> LocationService:
        """
        Return a ``LocationService`` instance for the given device.

        The concrete type depends on the iOS version:

        * iOS 17+  ->  ``DvtLocationService`` (uses DVT instrumentation)
        * iOS < 17 ->  ``LegacyLocationService`` (uses DtSimulateLocation)

        The service is cached on the connection so subsequent calls are cheap.
        """
        udid = self.canonical_udid(udid)
        async with self._lock:
            conn = self._connections.get(udid)

        if conn is None:
            raise RuntimeError(
                f"Device {udid} is not connected. Call connect() first."
            )

        if conn.location_service is not None:
            return conn.location_service

        ver = _parse_ios_version(conn.ios_version)
        if ver >= (17, 0):
            loc = await self._create_dvt_location_service(conn)
        else:
            loc = await self._create_legacy_location_service(conn)
        conn.location_service = loc
        return loc

    async def _ensure_personalized_ddi_mounted(self, conn: _ActiveConnection) -> None:
        """Check whether the Personalized DDI is mounted on the iPhone.

        v0.2.58 change: LocWarp no longer auto-downloads / auto-mounts
        the DDI. On iOS 26.4.1 the 20MB image upload routinely dropped
        the RSD tunnel mid-transfer, poisoning subsequent DVT calls
        with InvalidService. We now rely on the iPhone already having
        the DDI mounted (Xcode, 3uTools, 愛思助手, pymobiledevice3 CLI,
        or an earlier successful mount that iOS is still caching).

        This method is therefore a pure status check. If the iPhone
        has DDI mounted we log it and return happily. If not, we emit
        a WS event so the UI can tell the user to mount it via another
        tool, and we return anyway — the caller (`_create_dvt_location_service`)
        will then attempt DVT directly and produce a clean error if
        dtservicehub isn't advertised.
        """
        try:
            from pymobiledevice3.services.mobile_image_mounter import MobileImageMounterService
        except ImportError as exc:
            logger.warning(
                "pymobiledevice3 mobile_image_mounter not importable (%s: %s); "
                "skipping DDI status check", type(exc).__name__, exc,
            )
            return

        mounted = False
        try:
            mounter = MobileImageMounterService(lockdown=conn.lockdown)
            try:
                await mounter.connect()
                mounted = await mounter.is_image_mounted("Personalized")
            finally:
                try:
                    await mounter.close()
                except Exception:
                    pass
        except Exception:
            logger.warning("Could not query DDI mount status on %s", conn.udid, exc_info=True)
            return

        if mounted:
            logger.info("Personalized DDI already mounted on %s; DVT should work", conn.udid)
            try:
                from api.websocket import broadcast
                await broadcast("ddi_mounted", {"udid": conn.udid})
            except Exception:
                pass
            return

        logger.warning(
            "Personalized DDI is NOT mounted on %s. LocWarp will not "
            "auto-mount; please mount DDI for this iPhone first, then "
            "reconnect.", conn.udid,
        )
        try:
            from api.websocket import broadcast
            await broadcast("ddi_not_mounted", {
                "udid": conn.udid,
                "hint": (
                    "iPhone 上未偵測到 DDI。請先為這支 iPhone 掛載一次 DDI(Developer Disk Image),"
                    "再重新連接 LocWarp;或先重開 iPhone 後再試。"
                ),
            })
        except Exception:
            pass

    async def _ensure_classic_ddi_mounted(self, conn: _ActiveConnection) -> None:
        """Best-effort Developer Disk Image mount for iOS 16.x devices."""
        try:
            import pymobiledevice3.services.mobile_image_mounter as mim
        except ImportError as exc:
            logger.warning(
                "mobile_image_mounter not importable for classic DDI (%s: %s); "
                "skipping classic DDI mount",
                type(exc).__name__, exc,
            )
            return

        mounter_cls = getattr(mim, "MobileImageMounterService", None)
        if mounter_cls is not None:
            try:
                mounter = mounter_cls(lockdown=conn.lockdown)
                try:
                    await mounter.connect()
                    if await mounter.is_image_mounted("Developer"):
                        logger.debug("Classic DDI already mounted on %s", conn.udid)
                        return
                finally:
                    try:
                        await mounter.close()
                    except Exception:
                        pass
            except Exception:
                logger.warning("Could not query classic DDI mount state", exc_info=True)

        mount_fn = None
        for name in ("auto_mount_developer", "auto_mount", "auto_mount_disk_image"):
            candidate = getattr(mim, name, None)
            if callable(candidate):
                mount_fn = candidate
                break
        if mount_fn is None:
            logger.warning("No classic DDI auto-mount helper found; continuing without mount")
            return

        logger.info("Classic DDI not mounted on %s; attempting auto-mount", conn.udid)
        try:
            from api.websocket import broadcast
            await broadcast("ddi_mounting", {"udid": conn.udid})
        except Exception:
            pass

        mounted = False
        try:
            await asyncio.wait_for(mount_fn(conn.lockdown), timeout=120.0)
            mounted = True
            logger.info("Classic DDI mounted successfully for %s", conn.udid)
        except Exception:
            logger.warning("Classic DDI auto-mount failed for %s", conn.udid, exc_info=True)
        finally:
            try:
                from api.websocket import broadcast
                event = "ddi_mounted" if mounted else "ddi_mount_failed"
                payload = {"udid": conn.udid}
                if not mounted:
                    payload["error"] = "Classic DDI mount failed"
                await broadcast(event, payload)
            except Exception:
                pass

    async def _create_dvt_location_service(
        self, conn: _ActiveConnection, *, strict: bool = False
    ) -> DvtLocationService:
        """Spin up a DVT provider and hand it to ``DvtLocationService``.

        If DVT fails because the Developer Disk Image is not mounted,
        we try to mount it automatically and retry once.
        """
        # Try to mount DDI proactively (fast no-op when already mounted).
        try:
            await self._ensure_personalized_ddi_mounted(conn)
        except Exception:
            logger.warning("DDI auto-mount failed; DVT may still fail", exc_info=True)

        try:
            dvt = DvtProvider(conn.lockdown)
            conn.dvt_provider = dvt
            await dvt.__aenter__()
            logger.debug("DVT provider opened for %s", conn.udid)
            # Bind a per-udid factory so DvtLocationService._reconnect can
            # ask us for a fresh DvtProvider on the *current* lockdown.
            # This is what makes the location service survive WiFi tunnel
            # restarts — when the tunnel watchdog rebuilds the tunnel and
            # replaces conn.lockdown, the factory picks up the new one
            # automatically instead of rebuilding on a now-orphan ref.
            udid = conn.udid

            async def _factory(_udid: str = udid) -> DvtProvider:
                return await self.get_fresh_dvt_provider(_udid)

            service = DvtLocationService(
                dvt,
                lockdown=conn.lockdown,
                dvt_factory=_factory,
            )
            if strict:
                # Open the instrument without pushing a GPS coordinate.
                await service._ensure_instrument()
            return service
        except Exception as dvt_exc:
            if strict:
                raise
            logger.warning(
                "DVT location service failed for %s (%s). Falling back to "
                "legacy DtSimulateLocation over lockdown.",
                conn.udid, dvt_exc,
            )
            # iOS 17+ still exposes com.apple.dt.simulatelocation on some
            # devices (reported working on iOS 26 by multiple users), so
            # try the legacy service before giving up entirely.
            try:
                # Prefer the original usbmux/TCP lockdown for DtSimulateLocation;
                # fall back to whatever we have stored if not available.
                legacy_lockdown = conn.usbmux_lockdown or conn.lockdown
                legacy = LegacyLocationService(legacy_lockdown)
                logger.info("Using LegacyLocationService fallback for %s", conn.udid)
                return legacy
            except Exception:
                logger.exception(
                    "Both DVT and legacy location services failed for %s", conn.udid
                )
                raise dvt_exc

    async def _create_legacy_location_service(
        self, conn: _ActiveConnection
    ) -> LegacyLocationService:
        """Build the legacy location service for iOS 16.x devices."""
        try:
            await self._ensure_classic_ddi_mounted(conn)
        except Exception:
            logger.warning("Classic DDI auto-mount failed; legacy location may still fail", exc_info=True)
        logger.info("Using LegacyLocationService for %s", conn.udid)
        return LegacyLocationService(conn.lockdown)

    # _ensure_classic_ddi_mounted, _create_legacy_location_service, and
    # connect_wifi (legacy direct-IP WiFi) removed in v0.1.49 — see
    # UnsupportedIosVersionError. iOS 17+ continues to use the
    # personalized DDI mount path + DvtLocationService (with
    # LegacyLocationService as a runtime fallback inside
    # _create_dvt_location_service when DVT itself fails).

    # ------------------------------------------------------------------
    # WiFi connection (iOS 17+ tunnel only)
    # ------------------------------------------------------------------

    async def connect_wifi_tunnel(
        self, rsd_address: str, rsd_port: int
    ) -> DeviceInfo:
        """Connect to a device via an existing WiFi tunnel.

        Use this when a WiFi tunnel has already been established (by the
        in-process ``TunnelRunner`` or ``pymobiledevice3 remote start-tunnel``).
        The caller provides the RSD address and port.

        Returns a ``DeviceInfo`` describing the connected device.
        """
        logger.info("Connecting via WiFi tunnel RSD at %s:%d", rsd_address, rsd_port)

        import asyncio as _asyncio
        rsd = None
        last_exc: Exception | None = None
        # TUN interface routes may take a few seconds to become reachable
        # after the tunnel process reports ready, so retry with backoff.
        for attempt in range(1, 11):
            rsd = RemoteServiceDiscoveryService((rsd_address, rsd_port))
            try:
                await rsd.connect()
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "RSD connect attempt %d/10 failed (%s): %s",
                    attempt, exc.__class__.__name__, exc,
                )
                try:
                    await rsd.close()
                except (OSError, ConnectionError):
                    pass
                await _asyncio.sleep(min(0.5 * attempt, 2.0))

        if last_exc is not None:
            logger.error("Failed to connect to RSD at %s:%d after retries", rsd_address, rsd_port)
            raise RuntimeError(
                f"無法連線到 WiFi tunnel RSD ({rsd_address}:{rsd_port})。"
                "請確認 WiFi tunnel 仍然活躍。"
            ) from last_exc

        peer = rsd.peer_info or {}
        props = peer.get("Properties", {})
        udid = props.get("UniqueDeviceID", "")
        ios_version_str = props.get("OSVersion", "0.0")
        # peer_info["Properties"] only carries DeviceClass ("iPhone"), not
        # the user-set DeviceName (e.g. "My iPhone"). RSD.connect() already
        # opens a lockdown service over the tunnel internally and exposes
        # the result as rsd.all_values, so the live DeviceName is right
        # there for free. We still keep two fallbacks for the edge case
        # where the lockdown sub-service failed (e.g. RemoteXPC variants
        # that don't advertise it): a still-active USB conn's cached name,
        # then the persisted ~/.locwarp/device_names.json populated
        # whenever USB or discovery saw a real DeviceName.
        all_values = getattr(rsd, "all_values", None) or {}
        device_name = all_values.get("DeviceName") or ""
        if not device_name:
            existing = self._connections.get(udid)
            if existing is not None and existing.name and existing.name != "iPhone":
                device_name = existing.name
        if not device_name:
            cached = _load_device_name_cache().get(udid)
            if cached:
                device_name = cached
        if not device_name:
            device_name = props.get("DeviceClass", "iPhone")
        # Live DeviceName from the WiFi tunnel is just as authoritative as
        # USB, so feed it back into the persistent cache too — covers the
        # "user renamed the device since last USB plug" case.
        _remember_device_name(udid, device_name)

        if udid in self._connections:
            await self.disconnect(udid)

        conn = _ActiveConnection(
            udid=udid,
            lockdown=rsd,
            ios_version=ios_version_str,
            connection_type="Network",
            name=device_name,
            rsd=rsd,
        )

        async with self._lock:
            self._connections[udid] = conn

        logger.info("WiFi tunnel connected to %s (iOS %s)", udid, ios_version_str)

        return DeviceInfo(
            udid=udid,
            name=device_name,
            ios_version=ios_version_str,
            connection_type="Network",
            is_connected=True,
        )

    async def scan_wifi_devices(
        self,
        subnet: str | None = None,
        timeout: float = 0.5,
    ) -> list[dict]:
        """Scan the local network for iOS devices on port 62078 (lockdownd).

        Tries each IP in the subnet concurrently.  Returns a list of
        ``{"ip": ..., "name": ..., "udid": ...}`` dicts for reachable
        devices.

        If *subnet* is not given, the local machine's subnet is guessed
        from the default route interface.
        """
        if subnet is None:
            subnet = _guess_local_subnet()
            if subnet is None:
                logger.warning("Cannot determine local subnet for WiFi scan")
                return []

        logger.info("Scanning subnet %s for iOS devices...", subnet)

        # Generate IPs: e.g. "192.168.1" → .1 to .254
        base = subnet.rsplit(".", 1)[0]
        ips = [f"{base}.{i}" for i in range(1, 255)]

        async def _probe(ip: str) -> dict | None:
            try:
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip, 62078),
                    timeout=timeout,
                )
                writer.close()
                await writer.wait_closed()
                # Port is open — try a quick lockdown to get device info
                try:
                    pair_rec = _load_pair_record()
                    lockdown = await asyncio.wait_for(
                        create_using_tcp(
                            ip,
                            pair_record=pair_rec,
                            autopair=pair_rec is None,
                        ),
                        timeout=5.0,
                    )
                    vals = lockdown.all_values
                    return {
                        "ip": ip,
                        "name": vals.get("DeviceName", "Unknown"),
                        "udid": vals.get("UniqueDeviceID", lockdown.udid or ""),
                        "ios_version": vals.get("ProductVersion", "0.0"),
                    }
                except Exception:
                    # Port open but lockdown failed — still report it
                    return {"ip": ip, "name": "iOS Device", "udid": "", "ios_version": ""}
            except (OSError, asyncio.TimeoutError):
                return None

        results = await asyncio.gather(*[_probe(ip) for ip in ips])
        found = [r for r in results if r is not None]
        logger.info("WiFi scan found %d device(s)", len(found))
        return found

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @property
    def connected_udids(self) -> list[str]:
        """Return the UDIDs of all currently connected devices."""
        return list(self._connections.keys())

    def is_connected(self, udid: str) -> bool:
        """Check whether a device is currently connected."""
        return udid in self._connections

    def get_connection_type(self, udid: str) -> str:
        """Return ``'USB'`` or ``'Network'`` for a connected device."""
        conn = self._connections.get(udid)
        return conn.connection_type if conn else "USB"

    # ------------------------------------------------------------------
    # Recovery helpers (used by location_service factory + API safety net)
    # ------------------------------------------------------------------

    def connection_count(self) -> int:
        return len({u.lower() for u in self._connections}
                   | self._connection_reservations | set(self._native_recoveries))

    def is_native_wifi(self, udid: str) -> bool:
        conn = self._connections.get(udid)
        return (sys.platform == "darwin" and conn is not None
                and conn.connection_type == "Network" and conn.tunnel_context is not None
                and conn.tunnel_proxy is None)

    async def get_fresh_dvt_provider(
        self, udid: str, *, timeout: float = 15.0
    ) -> DvtProvider:
        """Return a freshly-opened ``DvtProvider`` for *udid*.

        Used by ``DvtLocationService._reconnect`` after the DVT instrument
        channel drops. Probes connection health, transparently waits for
        any in-flight WiFi tunnel restart driven by ``_per_tunnel_watchdog``
        (see ``api/device.py``), then opens a new ``DvtProvider`` on the
        *current* lockdown. The previous provider stored on the active
        connection is closed best-effort.

        Raises ``DeviceLostError`` (with a categorised ``reason``) when
        no live provider can be obtained inside *timeout* seconds —
        typically because the user really did unplug USB, turn off the
        iPhone, or the WiFi tunnel cannot be restarted.
        """
        import time
        deadline = time.monotonic() + timeout
        last_exc: Exception | None = None
        native = self.is_native_wifi(udid)
        generation = self._disconnect_generations.get(udid.lower(), 0)
        attempts = 0

        while True:
            async with self._lock:
                conn = self._connections.get(udid)

            if (conn is None or not self.auto_connect_allowed(udid)
                    or generation != self._disconnect_generations.get(udid.lower(), 0)):
                raise DeviceLostError(
                    f"Device {udid} no longer connected",
                    reason=DeviceLostError.REASON_USB_GONE,
                )

            # WiFi: peek at the tunnel runner. If it has died, the watchdog
            # is in the middle of restarting it — wait until either a fresh
            # runner appears (success path swaps in a new TunnelRunner and
            # replaces conn.lockdown along the way) or we time out.
            if conn.connection_type == "Network" and not native:
                runner = None
                try:
                    from api.device import _tunnels  # local import: avoids cycle at module load
                    runner = _tunnels.get(udid)
                except ImportError:
                    runner = None
                if runner is not None and not runner.is_running():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise DeviceLostError(
                            f"WiFi tunnel for {udid} did not restart in {timeout:.0f}s",
                            reason=DeviceLostError.REASON_TUNNEL_DEAD,
                        )
                    await asyncio.sleep(min(0.5, remaining))
                    continue

            # USB, or WiFi with a live tunnel: try opening a new DvtProvider.
            new_dvt = None
            try:
                attempts += 1
                new_dvt = DvtProvider(conn.lockdown)
                if native:
                    await asyncio.wait_for(new_dvt.__aenter__(), timeout=min(5.0, timeout))
                else:
                    await new_dvt.__aenter__()
            except BaseException as exc:
                try:
                    if new_dvt is not None:
                        await new_dvt.__aexit__(None, None, None)
                except Exception:
                    logger.debug("Failed to close unsuccessful DVT provider", exc_info=True)
                if not isinstance(exc, Exception):
                    raise
                last_exc = exc
                remaining = deadline - time.monotonic()
                if remaining <= 0 or (native and attempts >= 3):
                    logger.warning(
                        "get_fresh_dvt_provider exhausted for %s: %s", udid, exc,
                    )
                    raise DeviceLostError(
                        f"Could not open DvtProvider for {udid}: {exc}",
                        reason=DeviceLostError.REASON_LOCKDOWN_DEAD,
                    ) from exc
                await asyncio.sleep(min(0.5, remaining))
                continue

            if (self._connections.get(udid) is not conn
                    or not self.auto_connect_allowed(udid)
                    or generation != self._disconnect_generations.get(udid.lower(), 0)):
                await new_dvt.__aexit__(None, None, None)
                raise DeviceLostError("Connection changed during DVT recovery")

            # Success — swap into the active connection record so future
            # discover/clear paths find it. Best-effort close on the old.
            old_dvt = conn.dvt_provider
            conn.dvt_provider = new_dvt
            if old_dvt is not None and old_dvt is not new_dvt:
                try:
                    await old_dvt.__aexit__(None, None, None)
                except Exception:
                    logger.debug(
                        "Ignoring error closing stale DvtProvider for %s",
                        udid, exc_info=True,
                    )
            logger.info("DVT provider re-acquired for %s", udid)
            return new_dvt

    async def full_reconnect(self, udid: str) -> bool:
        """Last-resort recovery: force a complete teardown + reconnect.

        Used as the API-layer safety net (``api/location.py``) when the
        location service's factory-driven reconnect still raised
        ``DeviceLostError``. For WiFi this drives the same restart path
        the tunnel watchdog uses (rebuilding tunnel + RSD lockdown +
        DvtProvider). For USB, this disconnects + reconnects from
        scratch.

        Returns ``True`` when *udid* is healthily connected at exit.
        """
        async with self._lock:
            conn = self._connections.get(udid)
        conn_type = conn.connection_type if conn else None

        if self.is_native_wifi(udid) or udid.lower() in self._native_recoveries:
            key = udid.lower()
            task = self._native_recoveries.get(key)
            if task is None:
                from main import app_state
                task = asyncio.create_task(app_state.recover_native_wifi(udid))
                self._native_recoveries[key] = task
                def done(completed):
                    if self._native_recoveries.get(key) is completed:
                        self._native_recoveries.pop(key, None)
                task.add_done_callback(done)
            waiter = asyncio.current_task()
            generation = self._disconnect_generations.get(key, 0)
            waiters = self._native_recovery_waiters.setdefault(key, set())
            waiters.add(waiter)
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                if (not waiter.cancelling()
                        and generation != self._disconnect_generations.get(key, 0)):
                    return False
                raise
            finally:
                waiters.discard(waiter)
                if not waiters:
                    self._native_recovery_waiters.pop(key, None)

        if conn is None or not self.auto_connect_allowed(udid):
            return False
        if conn_type == "Network":
            try:
                from api.device import _tunnels, _attempt_tunnel_restart
            except ImportError:
                logger.debug("full_reconnect: api.device not importable")
                return False
            runner = _tunnels.get(udid)
            if runner is None or not runner.target_ip or not runner.target_port:
                logger.debug(
                    "full_reconnect: no live tunnel runner for %s; cannot recover", udid,
                )
                return False
            try:
                ok = await _attempt_tunnel_restart(
                    udid, runner.target_ip, runner.target_port, None, runner,
                )
                return bool(ok)
            except Exception:
                logger.exception("full_reconnect: WiFi tunnel restart failed for %s", udid)
                return False

        # USB (or unknown type — try the bluntest recovery available).
        try:
            try:
                await self.disconnect(udid)
            except Exception:
                logger.debug("full_reconnect: USB disconnect failed", exc_info=True)
            await self.connect(udid)
            async with self._lock:
                return udid in self._connections
        except Exception:
            logger.exception("full_reconnect: USB reconnect failed for %s", udid)
            return False

    async def disconnect_all(self) -> None:
        """Disconnect every active device."""
        udids = list(dict.fromkeys([*self._connections, *self._native_recoveries]))
        # Invalidate every pending recovery before awaiting any sibling cleanup.
        for udid in udids:
            key = udid.lower()
            self._disconnect_generations[key] = self._disconnect_generations.get(key, 0) + 1
        for udid in udids:
            await self.disconnect(udid)
        logger.info("All devices disconnected")


def _load_pair_record(udid: str | None = None) -> dict | None:
    """Load a USB pair record from Apple's system Lockdown store.

    On Windows, pair records live in ``%ALLUSERSPROFILE%\\Apple\\Lockdown``.
    If *udid* is given, loads that specific record; otherwise loads the
    first ``.plist`` found (most setups have only one device).
    """
    import os
    import plistlib

    lockdown_dir = Path(os.environ.get("ALLUSERSPROFILE", "C:/ProgramData")) / "Apple" / "Lockdown"
    if not lockdown_dir.exists():
        logger.debug("Apple Lockdown directory not found: %s", lockdown_dir)
        return None

    target: Path | None = None
    if udid:
        candidate = lockdown_dir / f"{udid}.plist"
        if candidate.exists():
            target = candidate
    else:
        # Pick the first device plist (skip SystemConfiguration.plist)
        for f in lockdown_dir.glob("*.plist"):
            if f.stem != "SystemConfiguration":
                target = f
                break

    if target is None:
        logger.debug("No pair record found in %s", lockdown_dir)
        return None

    try:
        with open(target, "rb") as fh:
            record = plistlib.load(fh)
        logger.debug("Loaded pair record from %s", target)
        return record
    except Exception:
        logger.exception("Failed to load pair record from %s", target)
        return None


def _guess_local_subnet() -> str | None:
    """Best-effort guess of the local LAN subnet (e.g. '192.168.1.0/24').

    Returns the base IP like '192.168.1.0' or ``None`` if unable to determine.
    """
    try:
        # Open a UDP socket to a public IP (doesn't actually send)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        # Return the /24 base
        parts = local_ip.rsplit(".", 1)
        return f"{parts[0]}.0"
    except (OSError, IndexError):
        return None

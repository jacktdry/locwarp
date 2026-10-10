/** Pure data interpretation for a renderer recreated during an active route.
 * No network requests, route planning or GPS writes are performed here. */
export type SnapshotPoint = { lat: number; lng: number }
export interface DeviceSnapshot {
  state: string
  simulation_kind?: string | null
  current_position?: SnapshotPoint | null
  route_path?: SnapshotPoint[] | null
  waypoints?: SnapshotPoint[] | null
  progress?: number
  eta_seconds?: number
  distance_remaining?: number
  distance_traveled?: number
  speed_mps?: number
  is_paused?: boolean
  segment_index?: number
  lap_count?: number
}
export interface BackendSnapshot {
  primary_udid?: string | null
  devices?: Record<string, DeviceSnapshot>
}

const activeStates = new Set(['navigating', 'looping', 'multi_stop', 'random_walk', 'flower', 'paused', 'joystick', 'reconnecting'])
export function validPosition(value: unknown): value is SnapshotPoint {
  if (!value || typeof value !== 'object') return false
  const p = value as SnapshotPoint
  return Number.isFinite(p.lat) && Number.isFinite(p.lng) &&
    Math.abs(p.lat) <= 90 && Math.abs(p.lng) <= 180
}
export function points(value: unknown): SnapshotPoint[] {
  return Array.isArray(value) ? value.filter(validPosition).map((p) => ({ lat: p.lat, lng: p.lng })) : []
}
export function normalizeDeviceSnapshot(raw: DeviceSnapshot) {
  const active = activeStates.has(raw.state)
  return {
    state: raw.state,
    active,
    paused: raw.is_paused === true || raw.state === 'paused',
    currentPos: validPosition(raw.current_position) ? { ...raw.current_position } : null,
    routePath: active ? points(raw.route_path) : [],
    waypoints: active ? points(raw.waypoints) : [],
    mode: active ? (raw.simulation_kind || (raw.state === 'multi_stop' ? 'multi_stop' : null)) : null,
    progress: Number.isFinite(raw.progress) ? raw.progress! : 0,
    eta: Number.isFinite(raw.eta_seconds) ? raw.eta_seconds! : 0,
    distanceRemaining: Number.isFinite(raw.distance_remaining) ? raw.distance_remaining! : 0,
    distanceTraveled: Number.isFinite(raw.distance_traveled) ? raw.distance_traveled! : 0,
    speed: Number.isFinite(raw.speed_mps) ? raw.speed_mps! : 0,
    waypointIndex: Number.isInteger(raw.segment_index) && raw.segment_index! >= 0 ? raw.segment_index! : null,
    lapCount: Number.isInteger(raw.lap_count) && raw.lap_count! >= 0 ? raw.lap_count! : 0,
  }
}

/** Merge a read-only HTTP snapshot with runtime events already observed by
 * this renderer. The HTTP response may have been captured *before* a newer
 * WebSocket position tick; do not rewind the marker, counters, or speed in
 * that case. Retain fields not present in the HTTP status (e.g. UI errors).
 * A completed/idle route must not retain destination overlays.
 */
export function mergeSnapshotRuntime<T extends {
  state: string
  currentPos: SnapshotPoint | null
  destination: SnapshotPoint | null
  routePath: SnapshotPoint[]
  progress: number
  eta: number
  distanceRemaining: number
  distanceTraveled: number
  currentSpeedKmh: number
  waypointIndex: number | null
  lapCount: number
}>(previous: T, raw: DeviceSnapshot, newerWsPosition = false): T {
  const snapshot = normalizeDeviceSnapshot(raw)
  const useLivePosition = newerWsPosition && previous.currentPos !== null
  return {
    ...previous,
    state: snapshot.state,
    currentPos: useLivePosition ? previous.currentPos : snapshot.currentPos,
    destination: snapshot.active ? previous.destination : null,
    routePath: snapshot.routePath,
    progress: useLivePosition ? previous.progress : snapshot.progress,
    eta: useLivePosition ? previous.eta : snapshot.eta,
    distanceRemaining: useLivePosition ? previous.distanceRemaining : snapshot.distanceRemaining,
    distanceTraveled: useLivePosition ? previous.distanceTraveled : snapshot.distanceTraveled,
    currentSpeedKmh: useLivePosition ? previous.currentSpeedKmh : snapshot.speed * 3.6,
    waypointIndex: snapshot.active ? snapshot.waypointIndex : null,
    lapCount: snapshot.active ? snapshot.lapCount : 0,
  }
}
export function selectSnapshotDevice(snapshot: BackendSnapshot, preferred?: string | null): string | null {
  const devices = snapshot?.devices ?? {}
  if (preferred && Object.prototype.hasOwnProperty.call(devices, preferred)) return preferred
  if (snapshot?.primary_udid && Object.prototype.hasOwnProperty.call(devices, snapshot.primary_udid)) return snapshot.primary_udid
  return Object.keys(devices)[0] || null
}

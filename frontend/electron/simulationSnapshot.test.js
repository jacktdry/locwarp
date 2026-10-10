const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { stripTypeScriptTypes } = require('node:module')

async function moduleUnderTest() {
  const source = fs.readFileSync(path.resolve(__dirname, '../src/hooks/simulationSnapshot.ts'), 'utf8')
  const plain = stripTypeScriptTypes(source)
  return import('data:text/javascript;base64,' + Buffer.from(plain).toString('base64'))
}

test('Cmd+W restore keeps the primary route and both device positions', async () => {
  const { selectSnapshotDevice, normalizeDeviceSnapshot } = await moduleUnderTest()
  const snapshot = {
    primary_udid: 'iphone-a', devices: {
      'iphone-a': { state: 'multi_stop', simulation_kind: 'multi_stop',
        current_position: {lat:25.01,lng:121.2},
        route_path: [{lat:25,lng:121},{lat:25.01,lng:121.2}],
        waypoints: [{lat:25,lng:121},{lat:25.05,lng:121.3}], progress: 0.4,
        speed_mps: 5, distance_remaining: 350, distance_traveled: 100 },
      'iphone-b': { state: 'looping', simulation_kind: 'start_loop',
        current_position: {lat:25.02,lng:121.22},
        route_path: [{lat:25.03,lng:121.23},{lat:25.04,lng:121.24}] },
    }
  }
  assert.equal(selectSnapshotDevice(snapshot,null),'iphone-a')
  assert.equal(selectSnapshotDevice(snapshot,'iphone-b'),'iphone-b')
  const a=normalizeDeviceSnapshot(snapshot.devices['iphone-a'])
  const b=normalizeDeviceSnapshot(snapshot.devices['iphone-b'])
  assert.equal(a.active,true)
  assert.equal(a.mode,'multi_stop')
  assert.equal(a.waypoints.length,2)
  assert.equal(a.routePath.length,2)
  assert.equal(a.distanceRemaining,350)
  assert.equal(b.mode,'start_loop')
  assert.equal(b.currentPos.lng,121.22)
  assert.equal(b.routePath.length,2)
})

test('Paused routes remain visible; idle snapshots clear only active overlays', async () => {
  const { normalizeDeviceSnapshot, points, selectSnapshotDevice } = await moduleUnderTest()
  const active={state:'paused',is_paused:true,simulation_kind:'multi_stop',
    waypoints:[{lat:24,lng:120},{lat:25,lng:121}],
    route_path:[{lat:24,lng:120},{lat:999,lng:120},null,{lat:25,lng:121}]}
  const paused=normalizeDeviceSnapshot(active)
  assert.equal(paused.paused,true)
  assert.equal(paused.active,true)
  assert.equal(paused.routePath.length,2)
  assert.equal(paused.waypoints.length,2)
  assert.equal(points('nonsense').length,0)
  const idle=normalizeDeviceSnapshot({...active,state:'idle'})
  assert.equal(idle.active,false)
  assert.deepEqual(idle.routePath,[])
  assert.deepEqual(idle.waypoints,[])
  assert.equal(idle.mode,null)
  assert.equal(selectSnapshotDevice({devices:{}}),null)
})

test('WS reconnect epoch triggers a new read-only snapshot, not a GPS command', () => {
  const hook = fs.readFileSync(path.resolve(__dirname,'../src/hooks/useSimulation.ts'),'utf8')
  const ws = fs.readFileSync(path.resolve(__dirname,'../src/hooks/useWebSocket.ts'),'utf8')
  const app = fs.readFileSync(path.resolve(__dirname,'../src/App.tsx'),'utf8')
  assert.match(ws,/setConnectionEpoch\(\(n\) => n \+ 1\)/)
  assert.match(app,/ws\.connectionEpoch/)
  assert.match(hook,/getSimulationSnapshot\(\)/)
  assert.match(hook,/\[primaryUdid, connectionEpoch\]/)
  assert.doesNotMatch(hook.slice(hook.indexOf('api.getSimulationSnapshot().then('),hook.indexOf('// ── Group-mode fan-out helpers')), /api\.(multiStop|startLoop|navigate|teleport|restoreSim|stopSim)\(/)
})

test('a late HTTP snapshot cannot rewind a more recent per-phone WS position tick', async () => {
  const { mergeSnapshotRuntime } = await moduleUnderTest()
  const liveA = {
    udid: 'a', state: 'looping', currentPos: { lat: 25.0008, lng: 121.0008 },
    destination: { lat: 25.1, lng: 121.1 },
    routePath: [], progress: 0.8, eta: 7, distanceRemaining: 9,
    distanceTraveled: 80, currentSpeedKmh: 10, waypointIndex: 1,
    lapCount: 2, error: 'temporary warning', cooldown: 2,
  }
  const olderA = {
    state: 'looping', simulation_kind: 'start_loop',
    current_position: { lat: 25, lng: 121 },
    route_path: [{ lat: 25, lng: 121 }, { lat: 25.1, lng: 121.1 }],
    progress: 0.4, eta_seconds: 20, distance_remaining: 25,
    distance_traveled: 40, speed_mps: 2, segment_index: 1, lap_count: 2,
  }
  const preserved = mergeSnapshotRuntime(liveA, olderA, true)
  assert.deepEqual(preserved.currentPos, liveA.currentPos)
  assert.equal(preserved.distanceTraveled, 80)
  assert.equal(preserved.eta, 7)
  assert.equal(preserved.progress, 0.8)
  assert.equal(preserved.currentSpeedKmh, 10)
  assert.equal(preserved.routePath.length, 2)
  assert.equal(preserved.error, 'temporary warning')
  assert.deepEqual(preserved.destination, liveA.destination)
  assert.equal(preserved.lapCount, 2)
  assert.equal(preserved.waypointIndex, 1)
  assert.deepEqual(liveA.currentPos, { lat: 25.0008, lng: 121.0008 }, 'input must not mutate')
  const freshB = mergeSnapshotRuntime({ ...liveA, udid: 'b', currentPos: null }, olderA, true)
  assert.deepEqual(freshB.currentPos, olderA.current_position,
    'a new device without WS coordinates may still hydrate from HTTP')
})

test('a completed route snapshot clears per-phone route and target overlays', async () => {
  const { mergeSnapshotRuntime, normalizeDeviceSnapshot, selectSnapshotDevice } = await moduleUnderTest()
  const live = {
    udid: 'a', state: 'looping', currentPos: { lat: 25, lng: 121 },
    destination: { lat: 25.1, lng: 121.1 },
    routePath: [{ lat: 25, lng: 121 }], progress: 0.9, eta: 10,
    distanceRemaining: 100, distanceTraveled: 120, currentSpeedKmh: 10,
    waypointIndex: 2, lapCount: 3, error: null, cooldown: 0,
  }
  const disconnected = mergeSnapshotRuntime(live, {
    state: 'idle', current_position: null, route_path: live.routePath,
    segment_index: 2, lap_count: 3,
  })
  assert.equal(disconnected.state, 'idle')
  assert.deepEqual(disconnected.routePath, [])
  assert.equal(disconnected.destination, null)
  assert.equal(disconnected.waypointIndex, null)
  assert.equal(disconnected.lapCount, 0)
  assert.equal(selectSnapshotDevice({ primary_udid: 'a', devices: {} }), null,
    'an empty authoritative GET removes all ghost devices')
  assert.equal(normalizeDeviceSnapshot({state: 'paused', lap_count: 4, segment_index: 3}).lapCount, 4)
  assert.equal(normalizeDeviceSnapshot({state: 'paused', lap_count: 4, segment_index: 3}).waypointIndex, 3)
  assert.equal(normalizeDeviceSnapshot({state: 'paused', lap_count: -1, segment_index: -2}).lapCount, 0)
})

test('live device positions use per-UDID revisions; empty snapshot clears stale toolbar', () => {
  const hook = fs.readFileSync(path.resolve(__dirname,'../src/hooks/useSimulation.ts'),'utf8')
  assert.match(hook, /devicePositionRevisions\.current\[id\]/)
  assert.match(hook, /observedDevicePositions\[udid\]/)
  assert.match(hook, /mergeSnapshotRuntime\(/)
  const emptyCase = hook.slice(hook.indexOf('if (!chosen) {'), hook.indexOf('const state = normalizeDeviceSnapshot(records[chosen])'))
  assert.match(emptyCase, /running: false/)
  assert.match(emptyCase, /setRoutePath\(\[\]\)/)
  assert.doesNotMatch(emptyCase, /setWaypoints\(\[\]\)/, 'retain the unsaved route draft')
})

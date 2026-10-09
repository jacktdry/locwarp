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

const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const path = require('node:path')

function loadUpdater(platform) {
  const file = path.resolve(__dirname, '../src/components/UpdateChecker.tsx')
  const source = fs.readFileSync(file, 'utf8')
  const match = source.match(/export function isNewer\(a: string, b: string\): boolean \{([\s\S]*?)\n\}/)
  assert.ok(match, 'must locate the actual production comparator')
  const code = 'function isNewer(a, b) {' + match[1].replace('(v: string)', '(v)') + '\n}\nexports.isNewer = isNewer;'
  const exports = {}
  vm.runInNewContext(code, { exports, Infinity })
  return exports
}

test('macOS uses this fork and prerelease-aware update comparison', () => {
  const { isNewer } = loadUpdater('darwin')
  assert.equal(isNewer('v0.2.200-macos.2', '0.2.200-macos.1'), true)
  assert.equal(isNewer('v0.2.201-macos.1', '0.2.200-macos.1'), true)
  assert.equal(isNewer('v0.2.200-macos.1', '0.2.200-macos.1'), false)
  assert.equal(isNewer('v0.2.199', '0.2.200-macos.1'), false)
  assert.equal(isNewer('v0.2.200', '0.2.200-macos.1'), true)
  assert.equal(isNewer('nonsense', '0.2.200-macos.1'), false)
})

test('Windows update checker keeps upstream links; Mac checks this fork', () => {
  const code = fs.readFileSync(path.resolve(__dirname,'../src/components/UpdateChecker.tsx'),'utf8')
  assert.match(code,/MAC_REPO = 'jacktdry\/locwarp-macos'/)
  assert.match(code,/UPSTREAM_REPO = 'keezxc1223\/locwarp'/)
  assert.match(code,/releases\/\$\{mac \? '\?per_page=20' : 'latest'\}/)
  assert.match(code,/currentVersion = mac \? CURRENT : CURRENT.split/)
  assert.equal(typeof loadUpdater('win32').isNewer, 'function')
})

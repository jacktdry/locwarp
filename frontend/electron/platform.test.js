const { test } = require('node:test')
const assert = require('node:assert/strict')
const path = require('path')
const { backendExecutable, locatePc, macBackendError, applicationMenu } = require('./platform')
const config = require('../package.json').build

test('packaged backend stays outside asar and uses the host executable name', () => {
  for (const platform of ['darwin', 'win32', 'linux']) {
    assert.equal(backendExecutable('/App Resources', platform, false), null)
    assert.equal(backendExecutable('/App Resources', platform, true),
      path.join('/App Resources', 'backend', platform === 'win32' ? 'locwarp-backend.exe' : 'locwarp-backend'))
  }
})

test('macOS never spawns Windows Location and honestly returns IP source', async () => {
  const result = { ok: true, lat: 25, lng: 121, via: 'ipwho.is' }
  const windows = () => { throw new Error('must not invoke PowerShell') }
  assert.deepEqual(await locatePc('darwin', windows, async () => result), result)
  assert.match((await locatePc('darwin', windows, async () => null)).message, /Native desktop location is unavailable/)
})

test('Windows native success, denied permission and IP fallback remain intact', async () => {
  assert.equal((await locatePc('win32', async () => ({ ok: true }), async () => { throw Error('unexpected fallback') })).via, 'windows')
  assert.equal((await locatePc('win32', async () => ({ code: 'DENIED' }), async () => { throw Error('permission must be respected') })).code, 'DENIED')
  assert.equal((await locatePc('win32', async () => ({ code: 'NODATA' }), async () => ({ via: 'ipapi.co' }))).via, 'ipapi.co')
})

test('macOS missing backend has actionable bilingual instructions', () => {
  for (const locale of ['zh-TW', 'en-US']) {
    const error = macBackendError(locale, '/LocWarp.app/backend/locwarp-backend', 'EACCES')
    assert.match(error.detail, /build-macos.sh/)
    assert.match(error.detail, /arm64/)
    assert.match(error.detail, /x64/)
    assert.match(error.detail, /EACCES/)
    assert.doesNotMatch(error.detail, /Windows Defender|Program Files/)
  }
})

test('macOS File menu maps Command+W to native close-window, not App Quit', () => {
  const menu = applicationMenu('darwin')
  const file = menu.find(item => item.label === 'File')
  assert.ok(file, 'macOS needs a native File menu for Cmd+W')
  const close = file.submenu.find(item => item.role === 'close')
  assert.equal(close.accelerator, 'Command+W')
  assert.equal(close.label, 'Close Window')
  assert.equal(file.submenu.some(item => item.role === 'quit'), false)
  assert.equal(applicationMenu('win32'), null, 'do not change Windows menus')
})

test('macOS packages use per-architecture native bundles; Windows config is retained', () => {
  assert.equal(config.win.extraResources[0].from, '../dist-py/locwarp-backend')
  assert.equal(config.win.requestedExecutionLevel, 'requireAdministrator')
  assert.equal(config.win.target[0].target, 'nsis')
  assert.equal(config.mac.extraResources[0].from, '../dist-py/mac-${arch}/locwarp-backend')
  assert.equal(config.mac.extraResources[0].to, 'backend')
  for (const target of config.mac.target) assert.deepEqual(target.arch, ['arm64', 'x64'])
  assert.deepEqual(config.mac.target.map(t => t.target), ['dmg', 'zip'])
  assert.match(config.mac.extendInfo.NSLocalNetworkUsageDescription, /iPhone/)
  assert.equal(config.mac.icon, 'build/icon.icns')
  assert.equal(config.extraResources[0].from, '../LICENSE')
  assert.equal(applicationMenu('win32'), null)
  assert.ok(applicationMenu('darwin').some(item => item.role === 'appMenu'))
})

const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const Module = require('node:module')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const { transformSync } = require('rolldown/utils')

function panel(platform, props) {
  const file = path.resolve(__dirname, '../src/components/DeviceStatus.tsx')
  // Transform this component in memory with the already-installed Vite
  // transformer. No bundle, dev server, or production build is created.
  const source = fs.readFileSync(file, 'utf8')
    .replace("import React, { useState } from 'react';", "const React = require('react'); const { useState } = React;")
    .replace("import { createPortal } from 'react-dom';", "const { createPortal } = require('react-dom');")
    .replace(/^import .* from '\.\.\/services\/api';$/m,
      "const { wifiTunnelDiscover, wifiTunnelFindPort, wifiRepair, wifiKeepaliveGet, wifiKeepaliveSet } = require('../services/api');")
    .replace("import { useT } from '../i18n';", "const { useT } = require('../i18n');")
    .replace('export default DeviceStatus;', 'module.exports.default = DeviceStatus;')
  const output = transformSync(file, source, { jsx: { runtime: 'classic' } }).code
  const loaded = new Module(file, module)
  loaded.paths = module.paths
  const originalRequire = loaded.require.bind(loaded)
  loaded.require = (id) => {
    if (id === '../i18n') return { useT: () => (key) => key }
    if (id === '../services/api') return { wifiKeepaliveGet: async () => ({ enabled: true }) }
    return originalRequire(id)
  }
  const previousNavigator = Object.getOwnPropertyDescriptor(global, 'navigator')
  const previousStorage = global.localStorage
  Object.defineProperty(global, 'navigator', { configurable: true, value: { platform, userAgent: platform } })
  global.localStorage = { getItem: () => null }
  try {
    loaded._compile(output, file)
    return renderToStaticMarkup(React.createElement(loaded.exports.default, {
      device: null, devices: [], isConnected: false, onScan() {}, onSelect() {}, ...props
    }))
  } finally {
    if (previousNavigator) Object.defineProperty(global, 'navigator', previousNavigator)
    else delete global.navigator
    global.localStorage = previousStorage
  }
}

test('Mac native candidates can opt in while connected or offline, without tunnel status', () => {
  const html = panel('MacIntel', {
    devices: [
      { id: 'A', name: 'Connected phone', connectionType: 'Network', isConnected: true },
      { id: 'b', name: 'Offline phone', connectionType: 'Network', isConnected: false },
      { id: 'friend', name: 'Friend', connectionType: 'Network', isConnected: false },
    ], autoConnectUdids: ['a'], onToggleAutoConnect() {}, tunnels: [],
  })
  assert.match(html, /aria-label="wifi.mac_auto_connect Connected phone"/)
  assert.match(html, /aria-label="wifi.mac_auto_connect Offline phone"/)
  assert.equal((html.match(/aria-pressed="true"/g) || []).length, 1)
  assert.equal((html.match(/aria-pressed="false"/g) || []).length, 2)
  assert.match(html, /status.connected/)
  assert.match(html, /status.disconnected/)
  assert.doesNotMatch(html, /wifi.tunnel_start/)
})

test('Mac cap disables new approval while keeping existing pins removable', () => {
  const html = panel('MacIntel', {
    devices: [{ id: 'a', name: 'Pinned', connectionType: 'Network' },
      { id: 'friend', name: 'Friend', connectionType: 'Network' }],
    autoConnectUdids: ['a', 'b', 'c'], onToggleAutoConnect() {},
  })
  assert.match(html, /aria-pressed="false" aria-label="wifi.mac_auto_connect Friend" disabled=""/)
  assert.doesNotMatch(html, /aria-pressed="true" aria-label="wifi.mac_auto_connect Pinned" disabled/)
})

test('Mac settings error is visible and a fresh preference is not implicitly approved', () => {
  const html = panel('MacIntel', {
    devices: [{ id: 'friend', name: 'Friend', connectionType: 'Network' }],
    autoConnectError: 'Unable to save', autoConnectBusy: true,
  })
  assert.match(html, /role="alert"[^>]*>Unable to save/)
  assert.doesNotMatch(html, /aria-pressed="true"/)
  assert.match(html, /aria-pressed="false"[^>]*disabled/)
})

test('Windows keeps its saved-IP panel and does not show native approval controls', () => {
  const html = panel('Win32', { onStartWifiTunnel() {},
    devices: [{ id: 'a', name: 'Phone', connectionType: 'Network' }], autoConnectUdids: ['a'] })
  assert.match(html, /wifi.section_title/)
  assert.doesNotMatch(html, /wifi.mac_auto_connect/)
})


test('Mac USB phone can opt in before unplugging for Wi-Fi fallback', () => {
  const html = panel('MacIntel', {
    devices: [{ id: 'usb-a', name: 'USB phone', connectionType: 'USB', isConnected: true },
      { id: 'wifi-b', name: 'WiFi phone', connectionType: 'Network', isConnected: false }],
    autoConnectUdids: ['usb-a'], onToggleAutoConnect() {}, tunnels: [],
  })
  assert.match(html, /aria-pressed="true" aria-label="wifi.mac_auto_connect USB phone"/)
  assert.match(html, /aria-pressed="false" aria-label="wifi.mac_auto_connect WiFi phone"/)
  assert.match(html, /wifi.mac_auto_connect_help/)
})

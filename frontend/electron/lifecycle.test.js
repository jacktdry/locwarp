const { test } = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const vm = require('node:vm')
const fs = require('node:fs')
const path = require('node:path')

test('closing and reactivating macOS windows retains one backend; Quit stops it', async () => {
  const app = new EventEmitter()
  let ready
  let windows = []
  const spawns = []
  const powerStarts = []
  const powerStops = []
  Object.assign(app, {
    getPath: () => '/test-user-data', getLocale: () => 'en-US', isPackaged: true,
    requestSingleInstanceLock: () => true,
    whenReady: () => ({ then: callback => { ready = callback } }),
    quit: () => app.emit('before-quit'),
  })
  class Window extends EventEmitter {
    constructor() {
      super()
      windows.push(this)
      this.webContents = new EventEmitter()
      this.webContents.setWindowOpenHandler = () => {}
    }
    loadFile() {}
    show() {}
    static getAllWindows() { return windows }
  }
  let kills = 0
  const electron = {
    app, BrowserWindow: Window,
    Menu: { setApplicationMenu: () => {}, buildFromTemplate: template => template },
    ipcMain: { handle: () => {} }, shell: {}, dialog: {},
    session: { defaultSession: { webRequest: { onBeforeSendHeaders: () => {} } } },
    powerSaveBlocker: {
      start: type => { powerStarts.push(type); return 0 },
      stop: id => { powerStops.push(id); return true },
    },
  }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'main.js'), 'utf8'), {
    require: name => {
      if (name === 'electron') return electron
      if (name === 'fs') return { readFileSync: () => { throw Error('absent') }, existsSync: () => true }
      if (name === './platform') return require('./platform')
      if (name === 'child_process') return { spawn: (...args) => {
        spawns.push(args)
        const child = new EventEmitter()
        child.stdout = new EventEmitter()
        child.stderr = new EventEmitter()
        child.kill = () => { kills++ }
        return child
      } }
      return require(name)
    },
    process: { platform: 'darwin', resourcesPath: '/LocWarp.app/Contents/Resources', argv: [], stdout: { write() {} }, stderr: { write() {} } },
    __dirname, console, setTimeout,
  })
  await ready()
  assert.equal(spawns.length, 1)
  assert.deepEqual(powerStarts, ['prevent-app-suspension'])
  assert.deepEqual(powerStops, [])
  assert.equal(spawns[0][0], '/LocWarp.app/Contents/Resources/backend/locwarp-backend')
  assert.deepEqual(Array.from(spawns[0][1]), [])
  windows = []
  app.emit('window-all-closed')
  assert.equal(kills, 0)
  assert.deepEqual(powerStops, [], 'Cmd+W must not allow sleep while the backend lives')
  app.emit('activate')
  assert.equal(spawns.length, 1)
  assert.equal(windows.length, 1)
  assert.equal(powerStarts.length, 1, 'Dock activation must not create a second blocker')
  app.emit('before-quit')
  assert.equal(kills, 1)
  assert.deepEqual(powerStops, [0], 'Cmd+Q must release even blocker ID 0')
  app.emit('before-quit')
  assert.deepEqual(powerStops, [0], 'Quit cleanup must not release the blocker twice')
})

test('a rejected second macOS instance never holds its own idle-sleep assertion', () => {
  const app = new EventEmitter()
  let quitCount = 0
  let starts = 0
  let stops = 0
  Object.assign(app, {
    getPath: () => '/test-user-data',
    getLocale: () => 'en-US',
    isPackaged: true,
    requestSingleInstanceLock: () => false,
    whenReady: () => { throw Error('rejected instance must not wait for Electron ready') },
    quit: () => { quitCount++; app.emit('before-quit') },
  })
  const electron = {
    app,
    BrowserWindow: { getAllWindows: () => [] },
    Menu: { setApplicationMenu: () => {}, buildFromTemplate: value => value },
    ipcMain: { handle: () => {} }, shell: {}, dialog: {},
    powerSaveBlocker: {
      start: () => { starts++; return 1 },
      stop: () => { stops++ },
    },
  }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'main.js'), 'utf8'), {
    require: name => {
      if (name === 'electron') return electron
      if (name === 'fs') return { readFileSync: () => { throw Error('not found') }, existsSync: () => true }
      if (name === './platform') return require('./platform')
      return require(name)
    },
    process: { platform: 'darwin', argv: [], resourcesPath: '/LocWarp.app/Contents/Resources' },
    __dirname, console, setTimeout,
  })
  assert.equal(quitCount, 1)
  assert.equal(starts, 0)
  assert.equal(stops, 0)
})

const fs = require('fs')
const path = require('path')
const { spawnSync } = require('child_process')
const MAGIC = new Set([0xfeedface, 0xfeedfacf, 0xcefaedfe, 0xcffaedfe, 0xcafebabe, 0xbebafeca, 0xcafebabf, 0xbfbafeca])

function signingTargets(app) {
  const files = [], bundles = []
  function walk(dir) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const file = path.join(dir, entry.name)
      if (entry.isSymbolicLink()) continue
      if (entry.isDirectory()) {
        walk(file)
        if (/\.(app|framework|xpc|bundle)$/.test(entry.name)) bundles.push(file)
      } else if (entry.isFile()) {
        const fd = fs.openSync(file, 'r'), header = Buffer.alloc(4)
        try { if (fs.readSync(fd, header, 0, 4, 0) === 4 && MAGIC.has(header.readUInt32BE())) files.push(file) }
        finally { fs.closeSync(fd) }
      }
    }
  }
  walk(app)
  return [...files, ...bundles, app]
}

function signLocalApp(app, run = spawnSync) {
  const deadline = Date.now() + 600000
  const targets = signingTargets(app)
  console.log(`Ad-hoc signing ${targets.length} code targets: ${app}`)
  for (const target of targets) {
    if (Date.now() >= deadline) throw new Error('Local codesign exceeded 600s; no archives produced')
    // Preserve valid PyInstaller signatures; the enclosing app is always sealed.
    const check = run('/usr/bin/codesign', ['--verify', '--strict', target], { timeout: 30000, encoding: 'utf8' })
    if (target !== app && !check.error && check.status === 0) continue
    const result = run('/usr/bin/codesign', ['--force', '--sign', '-', '--timestamp=none', '--preserve-metadata=entitlements', target], { timeout: 30000, encoding: 'utf8' })
    if (result.error || result.status !== 0) throw new Error(`Local codesign failed: ${target}\n${result.error?.message || result.stderr}`)
  }
  const verify = run('/usr/bin/codesign', ['--verify', '--deep', '--strict', app], { timeout: 60000, encoding: 'utf8' })
  if (verify.error || verify.status !== 0) throw new Error(`App signature verification failed: ${verify.error?.message || verify.stderr}`)
  console.log('ADHOC_CODESIGN_OK')
}

module.exports = { signingTargets, signLocalApp }

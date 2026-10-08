const fs = require('fs')
const path = require('path')
const { execFileSync } = require('child_process')
const { Arch } = require('builder-util')

// electron-builder otherwise permits an absent extraResources source.
// Reject missing, incomplete or wrong-architecture macOS backend inputs.
module.exports = async context => {
  if (context.electronPlatformName !== 'darwin') return
  const arch = Arch[context.arch]
  if (!['arm64', 'x64'].includes(arch)) throw new Error('Build separate arm64 and x64 macOS bundles')
  const root = path.resolve(context.packager.projectDir, '../dist-py', `mac-${arch}`, 'locwarp-backend')
  const exe = path.join(root, 'locwarp-backend')
  fs.accessSync(exe, fs.constants.X_OK)
  fs.accessSync(path.join(root, '_internal', 'static', 'phone.html'), fs.constants.R_OK)
  execFileSync('/usr/bin/lipo', ['-verify_arch', arch === 'x64' ? 'x86_64' : 'arm64', exe])
}

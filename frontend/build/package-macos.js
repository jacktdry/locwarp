const { spawnSync } = require('child_process')
const path = require('path')
const { signLocalApp } = require('./sign-local-app')

function signingPlan(env) {
  const mode = env.LOCWARP_MAC_SIGNING || 'local'
  const childEnv = { ...env }
  if (mode === 'local') {
    // Do not import certificates, query private keys or contact Apple during
    // a local build, even if this shell contains release credentials.
    for (const key of Object.keys(childEnv)) {
      if (key.startsWith('CSC_') || key.startsWith('APPLE_')) delete childEnv[key]
    }
    childEnv.CSC_IDENTITY_AUTO_DISCOVERY = 'false'
    return { env: childEnv, args: ['--config.mac.identity=null', '--config.mac.hardenedRuntime=false', '--config.mac.notarize=false', '--config.forceCodeSigning=false', '--config.compression=store'] }
  }
  if (mode !== 'developer-id') throw new Error('LOCWARP_MAC_SIGNING must be local or developer-id')
  const identity = env.LOCWARP_MAC_SIGNING_IDENTITY
  if (!identity?.startsWith('Developer ID Application:') || /[\r\n\0]/.test(identity)) {
    throw new Error('developer-id requires LOCWARP_MAC_SIGNING_IDENTITY=Developer ID Application: ...')
  }
  const notarization = env.APPLE_KEYCHAIN_PROFILE ||
    (env.APPLE_API_KEY && env.APPLE_API_KEY_ID && env.APPLE_API_ISSUER) ||
    (env.APPLE_ID && env.APPLE_APP_SPECIFIC_PASSWORD && env.APPLE_TEAM_ID)
  if (!notarization) throw new Error('developer-id requires complete notarization credentials or APPLE_KEYCHAIN_PROFILE')
  // v26 findIdentity rejects certificate-type prefixes in the qualifier.
  const qualifier = identity.slice('Developer ID Application:'.length).trim()
  if (!qualifier) throw new Error('Specify a Developer ID certificate name and team')
  return { env: childEnv, args: [`--config.mac.identity=${qualifier}`, '--config.mac.type=distribution', '--config.mac.hardenedRuntime=true', '--config.mac.notarize=true', '--config.forceCodeSigning=true'] }
}

// v26 accepts target names only immediately after the --mac array option.
function builderArgs(arch, plan, targets) {
  return ['--mac', ...targets, `--${arch}`, '--publish', 'never', ...plan.args]
}

if (require.main === module) {
  try {
    const plan = signingPlan(process.env)
    if (process.argv[2] !== '--check') {
      const arch = (process.argv[2] || process.arch).replace(/^--/, '')
      if (!['arm64', 'x64'].includes(arch)) throw new Error('Choose arm64 or x64')
      const project = path.resolve(__dirname, '..')
      const builder = args => {
        const result = spawnSync(process.execPath, [require.resolve('electron-builder/cli.js'), ...builderArgs(arch, plan, args)], { cwd: project, env: plan.env, stdio: 'inherit', timeout: 600000 })
        if (result.error || result.status !== 0) throw new Error(`electron-builder failed or exceeded 600s (${result.status ?? result.error?.code}); stop without retry`)
      }
      const dirOnly = process.env.LOCWARP_MAC_DIR_ONLY === '1'
      if ((process.env.LOCWARP_MAC_SIGNING || 'local') === 'local') {
        builder(['--dir'])
        const app = path.join(project, 'release', arch === 'arm64' ? 'mac-arm64' : 'mac', 'LocWarp.app')
        signLocalApp(app)
        if (!dirOnly) builder(['dmg', 'zip', '--prepackaged', app])
      } else {
        builder(dirOnly ? ['--dir'] : ['dmg', 'zip'])
      }
    }
  } catch (error) {
    console.error(error.message)
    process.exitCode = 1
  }
}

module.exports = { signingPlan, builderArgs }

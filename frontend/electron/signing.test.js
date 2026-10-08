const { test } = require('node:test')
const assert = require('node:assert/strict')
const { signingPlan, builderArgs } = require('../build/package-macos')

test('direct signing preserves valid backend code, seals outer app last and verifies', () => {
  const fs = require('fs'), path = require('path'), os = require('os')
  const { signingTargets, signLocalApp } = require('../build/sign-local-app')
  const app = fs.mkdtempSync(path.join(os.tmpdir(), 'locwarp-sign-test-'))
  try {
    const backend = path.join(app, 'backend')
    fs.writeFileSync(backend, Buffer.from([0xcf, 0xfa, 0xed, 0xfe]))
    const framework = path.join(app, 'Python.framework')
    fs.mkdirSync(framework)
    const python = path.join(framework, 'Python')
    fs.writeFileSync(python, Buffer.from([0xcf, 0xfa, 0xed, 0xfe]))
    fs.writeFileSync(path.join(app, 'data'), 'plain text')
    fs.symlinkSync('/outside/binary', path.join(app, 'external'))
    const targets = signingTargets(app)
    assert.ok(targets.indexOf(python) < targets.indexOf(framework))
    assert.equal(targets.at(-1), app)
    const calls = []
    signLocalApp(app, (command, args, options) => {
      calls.push(args)
      assert.ok(options.timeout <= 60000)
      // The executable is valid but its collected framework has no seal.
      return { status: args.includes('--verify') && !args.includes('--deep') && args.at(-1) === framework ? 1 : 0 }
    })
    const signs = calls.filter(args => args.includes('--sign'))
    assert.deepEqual(signs.map(args => args.at(-1)), [framework, app])
    assert.ok(signs[0].includes('--timestamp=none'))
    assert.deepEqual(calls.at(-1), ['--verify', '--deep', '--strict', app])
    assert.throws(() => signLocalApp(app, () => ({ status: 1, stderr: 'failure' })), /codesign failed/)
  } finally { fs.rmSync(app, { recursive: true, force: true }) }
})

test('local builds sign ad-hoc and never use inherited release credentials', () => {
  const env = { PATH: '/bin', CSC_LINK: 'secret', CSC_KEY_PASSWORD: 'secret', APPLE_ID: 'secret' }
  const plan = signingPlan(env)
  assert.ok(plan.args.includes('--config.mac.identity=null'))
  assert.ok(plan.args.includes('--config.forceCodeSigning=false'))
  assert.ok(plan.args.includes('--config.mac.notarize=false'))
  assert.deepEqual(plan.env, { PATH: '/bin', CSC_IDENTITY_AUTO_DISCOVERY: 'false' })
  assert.equal(env.CSC_LINK, 'secret')
})

test('release mode fails closed instead of falling back to local signing', () => {
  assert.throws(() => signingPlan({ LOCWARP_MAC_SIGNING: 'unknown' }))
  assert.throws(() => signingPlan({ LOCWARP_MAC_SIGNING: 'developer-id' }))
  assert.throws(() => signingPlan({ LOCWARP_MAC_SIGNING: 'developer-id', LOCWARP_MAC_SIGNING_IDENTITY: '-' }))
  const env = { LOCWARP_MAC_SIGNING: 'developer-id', LOCWARP_MAC_SIGNING_IDENTITY: 'Developer ID Application: Example (TEAM)' }
  assert.throws(() => signingPlan(env), /notarization/)
  const plan = signingPlan({ ...env, APPLE_KEYCHAIN_PROFILE: 'release' })
  assert.ok(plan.args.includes('--config.mac.identity=Example (TEAM)'))
  assert.ok(plan.args.includes('--config.mac.type=distribution'))
  assert.ok(plan.args.includes('--config.mac.hardenedRuntime=true'))
  assert.ok(plan.args.includes('--config.mac.notarize=true'))
  assert.ok(plan.args.includes('--config.forceCodeSigning=true'))
  assert.equal(plan.env.APPLE_KEYCHAIN_PROFILE, 'release')
})

test('v26 archive targets immediately follow --mac when using prepackaged app', () => {
  const plan = signingPlan({})
  const app = '/verified/LocWarp.app'
  assert.deepEqual(builderArgs('arm64', plan, ['dmg', 'zip', '--prepackaged', app]),
    ['--mac', 'dmg', 'zip', '--prepackaged', app, '--arm64', '--publish', 'never', ...plan.args])
  assert.deepEqual(builderArgs('x64', plan, ['--dir']).slice(0, 5),
    ['--mac', '--dir', '--x64', '--publish', 'never'])
})

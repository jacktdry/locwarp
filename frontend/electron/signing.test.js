const { test } = require('node:test')
const assert = require('node:assert/strict')
const { signingPlan, builderArgs, outputDirectory } = require('../build/package-macos')

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

test('default output preserves the existing builder argv and app path', () => {
  const path = require('path')
  const plan = signingPlan({})
  assert.equal(outputDirectory({}), 'release')
  assert.equal(path.join('/frontend', plan.output, 'mac-arm64', 'LocWarp.app'),
    '/frontend/release/mac-arm64/LocWarp.app')
  assert.deepEqual(builderArgs('arm64', plan, ['--dir']), [
    '--mac', '--dir', '--arm64', '--publish', 'never',
    '--config.mac.identity=null', '--config.mac.hardenedRuntime=false',
    '--config.mac.notarize=false', '--config.forceCodeSigning=false', '--config.compression=store'
  ])
})

test('isolated output parses with the installed builder CLI for dir and prepackaged stages', () => {
  const path = require('path')
  const { configureBuildCommand } = require('electron-builder/out/builder')
  for (const env of [
    { LOCWARP_MAC_OUTPUT_SUBDIR: 'UAT_arm64-01' },
    { LOCWARP_MAC_OUTPUT_SUBDIR: 'UAT_arm64-01', LOCWARP_MAC_SIGNING: 'developer-id',
      LOCWARP_MAC_SIGNING_IDENTITY: 'Developer ID Application: Example (TEAM)', APPLE_KEYCHAIN_PROFILE: 'release' }
  ]) {
    const plan = signingPlan(env)
    const app = path.join('/frontend', plan.output, 'mac-arm64', 'LocWarp.app')
    assert.equal(app, '/frontend/release/UAT_arm64-01/mac-arm64/LocWarp.app')
    for (const targets of [['--dir'], ['dmg', 'zip', '--prepackaged', app]]) {
      const argv = builderArgs('arm64', plan, targets)
      assert.equal(argv.at(-1), '--config.directories.output=release/UAT_arm64-01')
      const parsed = configureBuildCommand(require('yargs/yargs')(argv)).exitProcess(false).parse()
      assert.equal(parsed.config.directories.output, 'release/UAT_arm64-01')
      assert.equal(parsed.arm64, true)
      assert.equal(parsed.publish, 'never')
      assert.deepEqual(parsed._, [])
      if (targets[0] === '--dir') {
        assert.equal(parsed.dir, true)
        assert.deepEqual(parsed.mac, [])
        assert.equal(parsed.prepackaged, undefined)
      } else {
        assert.deepEqual(parsed.mac, ['dmg', 'zip'])
        assert.equal(parsed.prepackaged, app)
      }
    }
  }
})

test('output subdir rejects empty, traversal and non-ASCII input before building', () => {
  for (const subdir of ['', '.', '..', '../uat', 'uat/child', '/uat', 'uat\\child',
    'uat.v1', 'uat space', '驗收', 'uat\n', 'uat\r', 'uat\0', 'uat\t', 'uat=other']) {
    const env = { LOCWARP_MAC_OUTPUT_SUBDIR: subdir }
    assert.throws(() => signingPlan(env), /LOCWARP_MAC_OUTPUT_SUBDIR/)
    // NUL cannot be passed in an OS environment; the function still rejects it.
    if (subdir.includes('\0')) continue
    const result = require('child_process').spawnSync(process.execPath,
      [require.resolve('../build/package-macos'), '--check'],
      { env: { ...process.env, ...env, LOCWARP_MAC_SIGNING: 'local' }, encoding: 'utf8', timeout: 10000 })
    assert.equal(result.status, 1)
    assert.match(result.stderr, /LOCWARP_MAC_OUTPUT_SUBDIR/)
  }
  for (const subdir of ['a', '0', '_', '-', 'uat_01-ARM64']) {
    assert.equal(outputDirectory({ LOCWARP_MAC_OUTPUT_SUBDIR: subdir }), `release/${subdir}`)
  }
})

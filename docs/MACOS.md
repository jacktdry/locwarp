# macOS development and releases

This fork adds a native macOS packaging/startup path for Apple Silicon
(`arm64`) and Intel (`x64`). Windows NSIS, administrator startup and
Windows Location remain available. The upstream compatibility table is
Windows evidence, not macOS device certification. MIT attribution remains
in `LICENSE` and is copied into packaged resources.

## 開始使用 / device setup

macOS USB 使用 pymobiledevice3 11.26.0 以上的免 root 通道。請先用 USB
連接並解鎖 iPhone，在 Finder 與 iPhone 上完成「信任」；Mac 已內建 Apple
USB 服務，不需安裝 Windows 版 iTunes 驅動程式。iOS 16 以上需開啟
「設定 → 隱私權與安全性 → 開發者模式」，重新啟動後再確認。
開發者磁碟映像（DDI）必須符合裝置版本並掛載；LocWarp 會嘗試掛載，
若失敗可先使用相容版本的 Xcode 完成裝置準備。個人化 DDI 可能需要網路。
請勿將連線成功視為 DDI／定位服務已可用。

1. Use a data-capable USB cable. Unlock the device and approve Trust in
   Finder and on the device. macOS provides usbmuxd; Windows drivers are unnecessary.
2. Enable Settings → Privacy & Security → Developer Mode on iOS 16+;
   reboot and confirm. If absent, prepare the device with compatible Xcode
   or use the existing LocWarp Developer Mode action with your consent.
3. Ensure the matching Developer Disk Image is mounted. LocWarp attempts
   this, but a compatible Xcode device-preparation flow may be needed.
   Personalized DDI downloads need internet access.
4. Open the matching architecture app. USB iOS 17+ uses the library's
   `PreferredRsdTunnel`, keeping the tunnel handle alive until disconnect.
   It selects userspace transport and falls back to Apple's native remoted
   transport for older iOS 17 releases. No automatic elevation is performed.

## Development

Use a current Node.js supported by Vite 8 (22.12+ or a newer supported
release), npm, native Python **3.13**, and Apple's Command Line Tools
(`xcode-select --install` if not installed). Do not run setup concurrently
with the orchestrator's npm/uv installation. Reuse its `.venv` when available.

```bash
# Repository root; only when setup is not already in progress:
python3.13 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt 'pyinstaller>=6.19,<7'
cd frontend
npm ci
npm test
npm run build
cd ../backend
../.venv/bin/python -m unittest discover -s tests -v
../.venv/bin/python main.py --self-test
```

Run in two terminals:

```bash
# Terminal 1, repository root
cd backend
../.venv/bin/python main.py
```

```bash
# Terminal 2, repository root
cd frontend
npm start
```

Development Electron uses the manually started backend; packaged Electron
starts `Contents/Resources/backend/locwarp-backend` directly without a shell.
Data/logs live in the invoking user's `~/.locwarp/`. Cmd+Q stops the owned
backend. Closing the last macOS window keeps the app/backend alive;
clicking the Dock icon reopens a window without starting a second backend.
Do not start a second backend on port 8777 or kill an unrelated listener.
Stop your development backend with Ctrl+C before opening the packaged app.

## Build each architecture on matching macOS / Python

```bash
# Run npm ci once before this command (not concurrently).
bash build-macos.sh arm64    # Apple Silicon with arm64 Python 3.13
bash build-macos.sh x64      # Intel with x86_64 Python 3.13, on that host
```

The script checks Python version/architecture, creates a separate
`.venv-macos-<arch>`, installs requirements, tests Python, runs PyInstaller, runs the
hardware-free frozen `--self-test`, generates `icon.icns` from the existing
artwork, tests/builds the frontend, and packages DMG and ZIP with publishing
disabled. `LOCWARP_PYTHON=/path/to/python3.13` selects Python.
`LOCWARP_MAC_DIR_ONLY=1 bash build-macos.sh arm64` produces an unpacked app
for local packaging checks. PyInstaller does not cross-compile; an arm64
backend must never be shipped inside an x64 Electron app. The two output
trees are `dist-py/mac-arm64/locwarp-backend` and
`dist-py/mac-x64/locwarp-backend`. `npm run dist:mac -- --arm64` (or `--x64`)
only packages already built inputs and defaults to the Node host architecture.
A packaging hook rejects missing/incomplete or
wrong-architecture backend inputs before producing an app. Outputs are in `frontend/release/`, with the
architecture in each artifact name. No universal binary is claimed.

### Local ad-hoc signing (default)

`bash build-macos.sh arm64` and `npm run dist:mac -- --arm64` default to
`LOCWARP_MAC_SIGNING=local`: electron-builder first assembles `--dir` with
`identity=null`, hardened runtime off and notarization off. This intermediate
App is not accepted as signed. The local driver then uses `/usr/bin/codesign`
on nested Mach-O files and bundles as needed, preserving valid PyInstaller
signatures and existing entitlements, and seals the outer App last with
`--sign - --timestamp=none`. It requires `codesign --verify --deep --strict`
before archiving with electron-builder `--prepackaged`; that path does not
re-sign the App. Local archives use store compression for bounded build time.

Inherited `CSC_*` and `APPLE_*` credentials are removed from the packaging
child process. No private key access or permission dialogs are needed. Local
hardened runtime is off; SIP/Gatekeeper/TCC remain unchanged. The source
PyInstaller bundle is not modified. Invalid nested bundle seals (including
the collected Python framework) are repaired only in the assembled app; valid
backend executable signatures are retained. Each builder stage has a 600s timeout;
native signing has a 600s total deadline, 30s per command and 60s for final
verification. Failure stops the pipeline without automatic retries or archives
from an unverified App. The v26 osx-sign route stalled during local validation;
the local path deliberately avoids it and Apple's timestamp service.

Ad-hoc signing proves bundle integrity, not Apple trust. `spctl --assess --type
execute` may still reject these artifacts because they lack Developer ID and
notarization. Do not distribute them as trusted releases or change Gatekeeper
settings to make the assessment pass. No notarization is claimed.

For an app-only check with existing native backend and frontend build inputs:

```bash
cd frontend
LOCWARP_MAC_DIR_ONLY=1 npm run dist:mac -- --arm64
codesign --verify --deep --strict release/mac-arm64/LocWarp.app
# Full local pipeline assembles, signs, verifies, then creates DMG and ZIP:
npm run dist:mac -- --arm64
hdiutil verify release/LocWarp-*.dmg
unzip -tq release/LocWarp-*.zip
# An ad-hoc app may fail this assessment; it is not notarized:
spctl --assess --type execute --verbose=4 release/mac-arm64/LocWarp.app
```

Use the exact artifact filenames if multiple versions/architectures exist.
On Intel use `--x64` and `release/mac/LocWarp.app`. These checks do not
launch Electron, access a phone, or change security permissions.

### Developer ID release (explicit, fail closed)

For public distribution, configure a Developer ID Application certificate
with electron-builder's `CSC_LINK`/`CSC_KEY_PASSWORD` mechanism and its
notarization credentials (e.g. `APPLE_API_KEY`, `APPLE_API_KEY_ID`,
`APPLE_API_ISSUER`). Keep these outside source control. The default macOS
release mode enables hardened runtime, requires signing and notarization,
and rejects missing configuration rather than falling back to ad-hoc signing:

```bash
# Certificate/notarization credentials must already be configured securely.
LOCWARP_MAC_SIGNING=developer-id \
LOCWARP_MAC_SIGNING_IDENTITY='Developer ID Application: Your Name (TEAMID)' \
bash build-macos.sh arm64
```

Supply a complete API-key or Apple-ID credential set listed above, or use
`APPLE_KEYCHAIN_PROFILE` (and optional `APPLE_KEYCHAIN`) for an existing
notarytool profile. Select a certificate accessible without an interactive
private-key prompt in your release environment. Local checks do not exercise
this credential-dependent release mode. Unknown signing modes fail early.
The wrapper removes the certificate-type prefix for v26's identity qualifier.

For the release artifacts,
verify nested PyInstaller Mach-O libraries are signed, then verify the app
and DMG with `codesign --verify --deep --strict`, `spctl --assess --type execute`
and `xcrun stapler validate`. Test installation on a clean Mac of each
architecture. A local unsigned/ad-hoc build is not a notarized release.
Do not disable SIP, Gatekeeper or TCC, strip quarantine recursively, or
run the Electron GUI as root.

See the [electron-builder macOS reference](https://www.electron.build/v26/docs/mac/)
for signing/notarization and architecture settings. USB follows the
[pymobiledevice3 no-root Python API](https://github.com/doronz88/pymobiledevice3/blob/master/docs/guides/python-api.md);
the installed dependency source is the implementation reference.

## Permissions and known limitations

- **macOS Wi-Fi (native, no root):** pair/trust with Finder over USB and
  enable Wi-Fi connections, then unplug USB. When macOS `usbmuxd` reports
  the device with connection type `Network`, LocWarp now holds a
  `NativeRemotedTunnel(serial=udid)` via Apple's `remotepairingd`; it does
  not use the USB userspace PyTCP relay or the privileged kernel `utun`.
  Users may click **Scan devices** to reconnect an already-paired device;
  there is no Windows-style RemotePairing record repair on macOS. On some
  macOS versions, USBmux returns an empty list even when Apple's own
  remotepairingd can open a native RSD by serial; LocWarp also browses
  the authenticated native pairing records and can connect those Network
  candidates directly, without first creating a USBmux lockdown client.
  Paired records can be stale (offline devices) and Apple's
  `networkAdvertActive` may flip false when a phone sleeps; discovery
  therefore lists authenticated pairing records even without advertising.
  These are unverified candidates, not confirmed online phones, and the
  iOS version may remain unknown until an actual connection succeeds.
  Wi-Fi scan visibility is not proof of a working DVT service; the actual
  RSD connection and device location functions must still pass real UAT.
- The native tunnel shares Apple's single RSD link: Apple's `remoted` and
  LocWarp may temporarily evict each other's RSD sessions, affecting
  Xcode/devicectl and causing reconnects. Avoid concurrent device tools
  during tests. The standalone iOS 27.0.1 no-root native Wi-Fi RSD open and
  close passed real-device verification on 2026-10-09, but prolonged
  LocWarp GUI/position simulation stability has **not** yet passed UAT.
  Earlier macOS builds were observed driving CPU near 100% and causing API
  timeouts while a legacy Windows Wi-Fi auto-discovery flow also opened a
  Bonjour/mDNS UDP 5353 socket. The macOS UI no longer starts that Windows
  discovery loop and the backend rejects the legacy discovery/repair APIs
  on macOS. The native transport change and mDNS guard both still require
  real prolonged UAT to prove stable operation.
- The legacy manually-entered IP/RemotePairing tunnel runner still needs
  privileged kernel `utun` on macOS, so its Windows-oriented UI is hidden
  on Mac. Do not run the whole GUI as root. No privileged helper is bundled.
  For discovery use the same local network, allow LocWarp local-network
  access, and check VPN/HomiPlay routing, firewall, AP isolation and sleep.
- macOS **Locate PC uses only IP geolocation**, contacting the existing
  HTTPS providers on explicit button use. It exposes your public IP to
  those providers, may return a VPN exit city, and the displayed 5 km
  accuracy is a heuristic, not a measured confidence radius. There is no
  CoreLocation/GPS helper, so no location permission is requested or
  advertised. Results are labeled as IP; manual map selection works offline.
- pymobiledevice3's **USB** userspace transport has a process-wide
  singleton: one userspace iOS 17+ tunnel at a time. On 2026-10-09 the
  owner confirmed **two iPhones connected via native Wi-Fi simultaneously
  and both teleported successfully** on Apple Silicon. USB/native mixes,
  three-device combinations and Intel Mac remain unverified. Native remoted
  can conflict with concurrent Xcode/device tools as noted above.
- iOS 16 legacy transport is retained; all iPhone operations and Intel
  binaries still require real-device/host acceptance. Merely building or
  importing a bundle does not prove GPS simulation works.
- The existing backend listens on `0.0.0.0:8777` for phone control. Use a
  trusted LAN and firewall; do not expose this unauthenticated API to the
  internet. This port does not redesign that network contract.

## macOS window shortcuts

On macOS **File → Close Window** uses **⌘W**. This closes the focused
LocWarp window without quitting the app or stopping the location backend;
clicking the LocWarp Dock icon reopens the window. **⌘Q** quits the app and
stops its owned backend. Windows app/menu behavior is unchanged.

## Safe acceptance checks

Run the focused JS/Python tests and source/frozen `--self-test` first;
these do not discover or modify attached devices. Inspect both architecture
bundles with `file`/`lipo -info`, check executable permission and matching
Info.plist local-network descriptions. Verify app open, missing-backend
dialog, Cmd+Q, close/reopen, backend exit and a clean port on an isolated
machine **with no iPhone attached**. Device acceptance (USB trust, DDI,
disconnect/reconnect and any intentional GPS simulation) is a separate,
explicitly supervised activity. Wi-Fi, Intel runtime, Developer ID signing
and notarization remain separate release gates. In a Mac Wi-Fi UAT, keep
USB unplugged when launching the app, confirm `Network` + `is_connected`
from `/api/device/list`, verify a responsive API for at least several
minutes, then perform an explicit GPS teleport and restore only with the
owner present. USB-to-Wi-Fi hot handoff after removing the cable while a
userspace USB tunnel is active is a separate unverified stress case.

## Upstream synchronization — v0.2.200 (2026-10-09)

Merged upstream `main` (through `bac5bbb`, tag `v0.2.200`) into
`feature/macos-support` without replacing macOS-specific native Wi-Fi RSD,
USB/no-root handling, native pairing fallback, ad-hoc packaging, and
local-network permission declarations. Upstream changes are dependency
updates: pymobiledevice3 >=11.26, FastAPI >=0.143, Uvicorn >=0.54,
websockets >=17.2, Pydantic >=2.14; Electron 44.7 and MapLibre GL 6.13
are resolved by the new npm lockfile. Use a matching version field in
both `frontend/package.json` and `frontend/package-lock.json`.

The dependency upgrade does not itself verify remote/Wi-Fi GPS simulation.
Run local unit/build checks and frozen-backend self-test, then verify a
signed macOS app can launch and discover a previously paired iPhone,
without modifying its GPS during unattended smoke tests.

## macOS maintenance release and LAN API protections

This fork is published at https://github.com/jacktdry/locwarp-macos;
upstream Windows builds remain at https://github.com/keezxc1223/locwarp.
Release tag `v0.2.200-macos.1` is the first ARM64 **pre-release**, not an
Apple-trusted stable build. See [RELEASING.md](RELEASING.md) for branch,
versioning, test and signing gates.

Although the backend listens on `0.0.0.0:8777` to serve the optional
LAN phone-control page, the Mac/Desktop API and WebSocket are loopback-only.
Only explicit `/phone` and authenticated `/api/phone/*` routes are allowed
from LAN peers; the phone PIN login has rate limiting. A full public remote
control API has NOT been enabled. Do not expose port 8777 to the Internet.

## Route state recovery after macOS ⌘W

The macOS App intentionally keeps the backend simulation running when its
window is closed. On reopening from the Dock and whenever the WebSocket
reconnects, the renderer performs a read-only `GET /api/location/snapshot`.
The response contains the primary device, all connected devices' positions,
currently active route polylines and waypoints, progress and pause state.
Live WebSocket updates then continue from the existing backend; the snapshot
**does not** start, stop, teleport or replan an iPhone route. The HTTP
endpoint is restricted to the local Mac by the existing LAN access guard.

This fixes the renderer lifetime only; restarting the backend itself does
not preserve an in-progress simulation. New installed-App testing is deferred
until the user's ongoing route has completed to avoid interrupting GPS.

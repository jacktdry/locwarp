# macOS development and releases

This fork maintains a native macOS packaging/startup path **only for Apple
Silicon (`arm64`)**. Intel (`x64`) is **not a supported release target**;
legacy build switches may remain in the source but will not be maintained or
published. Windows NSIS, administrator startup and Windows Location remain available in the upstream project. The upstream compatibility table is
Windows evidence, not macOS device certification. MIT attribution remains
in `LICENSE` and is copied into packaged resources.

## 安裝、使用和 macOS Gatekeeper / Installation and Gatekeeper

首次使用者請先閱讀 [繁中 README：安裝、強制打開與基本使用](../README.md#安裝與首次開啟apple-silicon)
或 [English README: install, Open Anyway and basic use](../README.en.md#install-and-first-launch-apple-silicon)。
Apple 官方提供逐 App 的例外開啟方式：下載可信來源檔案、嘗試啟動後，到
**系統設定 → 隱私權與安全性 → 安全性 → 強制打開（Open Anyway）**；
不要全域停用 Gatekeeper、SIP 或移除安全隔離標記。若提示惡意軟體或
損毀，請停止並先確認來源。參閱 [Apple 官方說明](https://support.apple.com/zh-tw/102445)。

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

## Build on Apple Silicon (ARM64 macOS / Python)

```bash
# Run npm ci once before this command (not concurrently).
bash build-macos.sh arm64    # Apple Silicon with arm64 Python 3.13
```

The script checks Python version/architecture, creates a separate
`.venv-macos-<arch>`, installs requirements, tests Python, runs PyInstaller, runs the
hardware-free frozen `--self-test`, generates `icon.icns` from the existing
artwork, tests/builds the frontend, and packages DMG and ZIP with publishing
disabled. `LOCWARP_PYTHON=/path/to/python3.13` selects Python.
`LOCWARP_MAC_DIR_ONLY=1 bash build-macos.sh arm64` produces an unpacked app
for local packaging checks. PyInstaller does not cross-compile; the
ARM64 backend output is `dist-py/mac-arm64/locwarp-backend`.
`npm run dist:mac -- --arm64` only packages already built ARM64 inputs.
A packaging hook rejects missing/incomplete or
wrong-architecture backend inputs before producing an app. Outputs are in `frontend/release/`, with the
architecture in each artifact name. No universal binary is claimed.

### 獨立 ARM64 UAT 建置（已驗證）

2026-10-10 已在 Apple Silicon 完成一次隔離的 ARM64 全流程建置：
`LOCWARP_MAC_OUTPUT_SUBDIR=uat-61e4450` 且 `LOCWARP_MAC_DIR_ONLY=1`，
後端 78、Electron 24 項測試、frozen backend `--self-test`、前端 build、
App/後端 ARM64 架構及 `codesign --verify --deep --strict` 均通過。
產物位於 `frontend/release/uat-61e4450/mac-arm64/LocWarp.app`，未啟動驗收 App，
**不代表雙 iPhone 實機驗收已通過**。以下為可重現的建置命令；
先依上述流程準備相符的 ARM64 環境，不要與其他建置同時執行。

```bash
# Repository root: full pipeline, including PyInstaller; does not launch Electron.
LOCWARP_MAC_OUTPUT_SUBDIR=uat-arm64 LOCWARP_MAC_DIR_ONLY=1 bash build-macos.sh arm64
# Or package only, after matching backend/frontend inputs have already been built:
(cd frontend && LOCWARP_MAC_OUTPUT_SUBDIR=uat-arm64 LOCWARP_MAC_DIR_ONLY=1 npm run dist:mac -- --arm64)
codesign --verify --deep --strict frontend/release/uat-arm64/mac-arm64/LocWarp.app
```

`LOCWARP_MAC_OUTPUT_SUBDIR` 只允許非空的單層 ASCII 英數、底線、連字號；
不可含點、斜線、反斜線或空白。未設定時仍使用 `frontend/release/`，
預設 App 為 `frontend/release/mac-arm64/LocWarp.app`。
設定後兩次 electron-builder 階段及簽章／驗證均使用 `release/<subdir>/`；
搭配 `LOCWARP_MAC_DIR_ONLY=1` 只產生 unpacked App，不產生或覆寫歷史 DMG／ZIP。
重用同一 subdir 會重建該目錄內的 App，需保留的驗收產物請用不同名稱。
此隔離僅限封裝輸出：前端、PyInstaller 中間產物與 `~/.locwarp/` 執行資料仍共享。

不修改 `appId=com.locwarp.app` 或 `productName=LocWarp`。
正式版與驗收版具有相同 bundle ID、共享資料及連接埠 8777，**不可同時啟動**；
不要複製到或覆寫 `/Applications/LocWarp.app`。
雙 iPhone 及恢復流程請見 [macOS 多裝置 UAT](MACOS_MULTI_DEVICE_UAT.md)，
被動觀察與 GPS／路線／群組同步須分別取得同意，建置通過不代表實機通過。

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
Intel (`--x64`) builds are intentionally unsupported and not tested.
These checks do not launch Electron, access a phone, or change security permissions.

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
  and both teleported successfully** on Apple Silicon. USB/native mixes and
  three-device combinations remain unverified. Intel Mac is unsupported. Native remoted
  can conflict with concurrent Xcode/device tools as noted above.
- iOS 16 legacy transport is retained; all iPhone operations still
  require real-device acceptance. Merely building or
  importing a bundle does not prove GPS simulation works.
- The backend listens on `0.0.0.0:8777` for the optional phone page.
  Desktop API and WebSocket routes are loopback-only; LAN phone routes
  require PIN/token auth (except the public phone page). Use trusted Wi-Fi;
  do not expose port 8777 to the public Internet.

## macOS window shortcuts

On macOS **File → Close Window** uses **⌘W**. This closes the focused
LocWarp window without quitting the app or stopping the location backend;
clicking the LocWarp Dock icon reopens the window. **⌘Q** quits the app and
stops its owned backend. Windows app/menu behavior is unchanged.

## Safe acceptance checks

Run the focused JS/Python tests and source/frozen `--self-test` first;
these do not discover or modify attached devices. Inspect the ARM64 app and backend
with `file`/`lipo -info`, check executable permission and matching
Info.plist local-network descriptions. Verify app open, missing-backend
dialog, Cmd+Q, close/reopen, backend exit and a clean port on an isolated
machine **with no iPhone attached**. Device acceptance (USB trust, DDI,
disconnect/reconnect and any intentional GPS simulation) is a separate,
explicitly supervised activity. Wi-Fi runtime, Developer ID signing
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


## Pending next prerelease — approved-device automatic connection

Unreleased work on `feature/macos-connection-resilience`; this does not
change the verification claims for released `v0.2.200-macos.1`.

On macOS, each discovered USB or Wi-Fi device has an **Auto-connect** toggle,
including disconnected candidates. Before unplugging USB for Wi-Fi fallback,
pair in Finder and enable **Show this iPhone when on Wi-Fi**. Only explicitly selected UDIDs (maximum
three) are persisted as `auto_connect_udids` in `~/.locwarp/settings.json`.
Discovery and manual connection do not approve devices automatically. The
loopback-only settings API is `GET /api/device/auto-connect`, plus
`GET` / `POST /api/device/{udid}/auto-connect` (`{"enabled": true|false}`).

The backend starts serving before device discovery and supervises selected
paired devices while the window is closed. Shared discovery is paced at ten
seconds; each device has bounded connection/service attempts and failure
backoff from five seconds up to five minutes. Native records must have a
live advertisement or a matching Network entry in usbmux before an attempt;
the native handshake must still prove reachability. USB remains preferred
when attached. After normal USB unplug teardown, only opted-in devices can
fall back to reachable native Wi-Fi. Manual disconnect suppresses reconnect
for that process session until explicit connection; toggling Auto-connect
or scanning does not clear it. Existing Windows saved-IP pins are separate.

No Windows TUN runner, root permission, new pairing prompt, or periodic GPS
probe is used by the native supervisor. Group synchronization may reapply
the primary's user-selected position after a successful connection.
Physical UAT remains pending: two/three iPhones, offline return, USB-to-Wi-Fi
handoff, manual suppression, pin persistence, and closed-window operation.


Pending next prerelease USB transport note: pymobiledevice3 11.26.0 permits
one process-wide userspace RSD tunnel. The first USB iOS 17+ connection keeps
the tested PreferredRsdTunnel path; another USB uses a bounded no-root native
attempt while that userspace context is owned (including during handshake).
Native failure leaves existing phones connected and uses existing USB retry
backoff. iOS 16 legacy clients and native Wi-Fi handles do not occupy the
userspace slot. No privileged TUN fallback is started. Multiple USB phones
and mixed USB/Wi-Fi transport behavior remain pending physical UAT.

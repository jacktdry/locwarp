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
only packages already built inputs. Without an architecture flag, both
backend trees must exist. A packaging hook rejects missing/incomplete or
wrong-architecture backend inputs before producing an app. Outputs are in `frontend/release/`, with the
architecture in each artifact name. No universal binary is claimed.

For public distribution, configure a Developer ID Application certificate
with electron-builder's `CSC_LINK`/`CSC_KEY_PASSWORD` mechanism and its
notarization credentials (e.g. `APPLE_API_KEY`, `APPLE_API_KEY_ID`,
`APPLE_API_ISSUER`). Keep these outside source control. The default macOS
configuration retains hardened runtime and electron-builder signing;
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

- **Wi-Fi remains limited:** this repository's RemotePairing runner uses
  a kernel `utun`, requiring a privileged backend on macOS. A normal
  packaged app explicitly reports this requirement and directs users to
  USB. It does not prompt for sudo or run privileged scripts. An isolated,
  audited privileged backend/helper or a userspace Wi-Fi migration is
  future work; do not run the whole GUI as root. No end-to-end macOS Wi-Fi
  support is claimed by this port.
- For network discovery, pair/trust over USB first; use the same subnet,
  allow LocWarp local-network access in macOS Privacy & Security, and allow
  the required traffic through your firewall. The bundle declares local
  network usage and Bonjour service types. VPNs, AP isolation and sleeping
  devices can prevent discovery or drop tunnels. Permissions alone do not
  remove the current Wi-Fi `utun` limitation.
- macOS **Locate PC uses only IP geolocation**, contacting the existing
  HTTPS providers on explicit button use. It exposes your public IP to
  those providers, may return a VPN exit city, and the displayed 5 km
  accuracy is a heuristic, not a measured confidence radius. There is no
  CoreLocation/GPS helper, so no location permission is requested or
  advertised. Results are labeled as IP; manual map selection works offline.
- pymobiledevice3's userspace transport currently has a process-wide
  singleton: one userspace iOS 17+ device at a time on macOS. The upstream
  three-device claim has not been validated on this transport. Native
  remoted fallback can be sensitive to concurrent Xcode/device tools.
- iOS 16 legacy transport is retained; all iPhone operations and Intel
  binaries still require real-device/host acceptance. Merely building or
  importing a bundle does not prove GPS simulation works.
- The existing backend listens on `0.0.0.0:8777` for phone control. Use a
  trusted LAN and firewall; do not expose this unauthenticated API to the
  internet. This port does not redesign that network contract.

## Safe acceptance checks

Run the focused JS/Python tests and source/frozen `--self-test` first;
these do not discover or modify attached devices. Inspect both architecture
bundles with `file`/`lipo -info`, check executable permission and matching
Info.plist local-network descriptions. Verify app open, missing-backend
dialog, Cmd+Q, close/reopen, backend exit and a clean port on an isolated
machine **with no iPhone attached**. Device acceptance (USB trust, DDI,
disconnect/reconnect and any intentional GPS simulation) is a separate,
explicitly supervised activity. Wi-Fi, Intel runtime, Developer ID signing
and notarization remain separate release gates.

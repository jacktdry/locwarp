# LocWarp for macOS — release process

## Source ownership and Git flow

- `origin`: `https://github.com/jacktdry/locwarp-macos` (macOS maintenance fork).
- `upstream`: `https://github.com/keezxc1223/locwarp` (Windows-first original).
- `main`: macOS-maintained release branch and default repository view.
- `sync/upstream-vX.Y.Z`: **temporary** upstream integration branch, based on `main`.
- `feature/*`, `fix/*`: short-lived work branches; avoid using a permanent feature branch for public releases.

To update upstream: `git fetch upstream`; branch `sync/upstream-vX.Y.Z` from `main`; `git merge --no-ff upstream/main`; resolve conflicts while preserving macOS RSD, Wi-Fi discovery, local API protections, signing and packaging. Run Python tests, frontend tests and build, packaged-backend self-test, ARM64 codesign and DMG verification, then merge the sync branch back to `main`. Never force-update `upstream/main`.

## Version policy

Mac preview builds may append a SemVer pre-release suffix (e.g. `v0.2.200-macos.1`). For stable releases, **do not use a hyphen suffix**, which SemVer classifies as a pre-release: this macOS-only fork uses the next patch version `v0.2.201` based on upstream `v0.2.200`. Do not reuse upstream `v0.2.200` as the fork tag. Align `frontend/package.json`, `frontend/package-lock.json`, git tag, README, release notes and DMG/ZIP names. Create stable tags from the validated `main` branch, not a feature branch.

## ARM64 release validation gate

1. Verify clean checkout and explicit tag/commit, `node --test` and Python unit tests.
2. Build on **real Apple Silicon macOS** with native Python 3.13; do not cross-compile the Python backend. Run `npm ci` separately, then `bash build-macos.sh arm64`.
3. Assert App bundle version equals the tag, frozen-backend `--self-test`, `codesign --verify --deep --strict`, `unzip -tq`, `hdiutil verify`, app launches and backend answers 200 on loopback.
4. Verify LAN requests to `/api/device/list`, `/api/location/status`, and `/ws/status` are rejected, while `/phone` and authenticated `/api/phone/status` remain accessible; six-digit PIN guesses must be rate limited.
5. Confirm an iPhone connects via Wi-Fi (ideally two), location service ready, no unexpected CPU/mDNS regression. Explicitly supervised GPS tests only—never teleport unattended.
6. **Stable = product validation, not Apple trust certification.** The maintainer decided on 2026-10-10 to ship `v0.2.201` as a stable GitHub Release after ARM64 feature/UAT tests, **even while the app remains ad-hoc signed and NOT Apple-notarized**. This is an explicit macOS distribution choice and does **not** indicate Apple has verified its origin or safety. The README and Release Notes MUST state this prominently; display the Gatekeeper Open Anyway procedure for users who verify their download and wish to authorize this individual app. Do not recommend disabling Gatekeeper, SIP or TCC. Fail closed on malware/damaged-app warnings. Public consumer installation has more friction and risk than notarized builds; do not conceal this.
7. For future **Apple-verified distribution** (recommended to improve trust/installation), require a Developer ID Application certificate, hardened runtime, notarization and stapling. Then additionally validate `spctl --assess --type execute`, `xcrun stapler validate` and a clean-Mac install. Until that happens, `spctl` acceptance and `stapler` success are **not** claimed for ad-hoc stable builds. Never mislabel this distribution as notarized.

Use the manual GitHub Actions workflow `macos-verify.yml` for reproducible unit/build checks. It does **not** publish Releases or access Developer ID secrets. Do not publish artifacts from failed verification.

## Release assets

- `LocWarp-0.2.200-macos.1-mac-arm64.dmg`: installation image.
- `LocWarp-0.2.200-macos.1-mac-arm64.zip`: optional archive.
- `SHA256SUMS.txt`: checksums.

For `v0.2.201`, use GitHub **stable** (non-draft, `prerelease=false`, `make_latest=true`) despite the explicit ad-hoc / non-notarized caveat above. Set the tag to the tested main commit and attach DMG, ZIP, SHA256SUMS. Distinguish this macOS build from upstream Windows Releases. Electron checks this fork's releases on macOS; Windows checks upstream.

## Security and remote control

Local desktop APIs (`/api/device`, `/api/location`, `/ws/status`, etc.) are loopback-only **by socket peer address**, despite the backend binding on the LAN for `/phone`. The remote `/phone` UI exposes only specified `/api/phone/*` routes. PIN attempts are rate limited; phone actions require a bearer token. LAN HTTP PIN/token control still lacks transport encryption and is intended for trusted Wi-Fi only. Do not expose TCP 8777 on public networks, via Tailscale Funnel or a public tunnel. A remote-agent mode needs separate authenticated TLS, permissions and lifecycle design.

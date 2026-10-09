# LocWarp for macOS — release process

## Source ownership and Git flow

- `origin`: `https://github.com/jacktdry/locwarp-macos` (macOS maintenance fork).
- `upstream`: `https://github.com/keezxc1223/locwarp` (Windows-first original).
- `main`: macOS-maintained release branch and default repository view.
- `sync/upstream-vX.Y.Z`: **temporary** upstream integration branch, based on `main`.
- `feature/*`, `fix/*`: short-lived work branches; avoid using a permanent feature branch for public releases.

To update upstream: `git fetch upstream`; branch `sync/upstream-vX.Y.Z` from `main`; `git merge --no-ff upstream/main`; resolve conflicts while preserving macOS RSD, Wi-Fi discovery, local API protections, signing and packaging. Run Python tests, frontend tests and build, packaged-backend self-test, ARM64 codesign and DMG verification, then merge the sync branch back to `main`. Never force-update `upstream/main`.

## Version policy

Keep the full upstream base number, add a macOS maintenance suffix, e.g. `v0.2.200-macos.1`, then `v0.2.200-macos.2` or `v0.2.201-macos.1`. Ensure `frontend/package.json`, `frontend/package-lock.json`, git tag and DMG name agree. Do not reuse the upstream `v0.2.200` tag. GitHub Releases may target a non-default branch, but stable macOS releases are created from `main` after validation.

## ARM64 pre-release gate

1. Verify clean checkout and explicit tag/commit, `node --test` and Python unit tests.
2. Build on **real Apple Silicon macOS** with native Python 3.13; do not cross-compile the Python backend. Run `npm ci` separately, then `bash build-macos.sh arm64`.
3. Assert App bundle version equals the tag, frozen-backend `--self-test`, `codesign --verify --deep --strict`, `unzip -tq`, `hdiutil verify`, app launches and backend answers 200 on loopback.
4. Verify LAN requests to `/api/device/list`, `/api/location/status`, and `/ws/status` are rejected, while `/phone` and authenticated `/api/phone/status` remain accessible; six-digit PIN guesses must be rate limited.
5. Confirm an iPhone connects via Wi-Fi (ideally two), location service ready, no unexpected CPU/mDNS regression. Explicitly supervised GPS tests only—never teleport unattended.
6. The current pre-release artifact is **ad-hoc signed and NOT notarized**. Public release notes MUST disclose Gatekeeper rejection, Apple non-verification and Intel untested. This is for advanced testers, not a stable/official release. Do not recommend disabling Gatekeeper, SIP or TCC to bypass it.
7. A public stable release requires a **Developer ID Application** certificate, hardened runtime, Apple notarization and stapling. Validate `spctl --assess --type execute` and `xcrun stapler validate` plus installation on a clean Mac.

Use the manual GitHub Actions workflow `macos-verify.yml` for reproducible unit/build checks. It does **not** publish Releases or access Developer ID secrets. Do not publish artifacts from failed verification.

## Release assets

- `LocWarp-0.2.200-macos.1-mac-arm64.dmg`: installation image.
- `LocWarp-0.2.200-macos.1-mac-arm64.zip`: optional archive.
- `SHA256SUMS.txt`: checksums.

Use a **pre-release** flag until Apple signing and notarization are complete. Distinguish this macOS build from upstream Windows Releases. Electron checks this fork's releases (including pre-releases) on macOS; Windows checks upstream.

## Security and remote control

Local desktop APIs (`/api/device`, `/api/location`, `/ws/status`, etc.) are loopback-only **by socket peer address**, despite the backend binding on the LAN for `/phone`. The remote `/phone` UI exposes only specified `/api/phone/*` routes. PIN attempts are rate limited; phone actions require a bearer token. LAN HTTP PIN/token control still lacks transport encryption and is intended for trusted Wi-Fi only. Do not expose TCP 8777 on public networks, via Tailscale Funnel or a public tunnel. A remote-agent mode needs separate authenticated TLS, permissions and lifecycle design.

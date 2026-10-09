# LocWarp for macOS

<p align="right"><a href="README.md">繁體中文</a> · <b>English</b></p>

<p align="center"><img src="frontend/build/icon.png" alt="LocWarp" width="112"></p>

**Simulate iPhone and iPad locations over USB or Wi-Fi on macOS.** This is a community-maintained macOS fork of the [original LocWarp](https://github.com/keezxc1223/locwarp), preserving navigation and GPS simulation and adding Apple-native RSD transport and Apple Silicon packaging.

> **Release status: ARM64 pre-release only.** Current Mac builds use **ad-hoc signing, not Apple Developer ID signing or notarization**. Gatekeeper may block installation. Intel Macs have not been tested. These testing builds are not Apple-verified.

**[macOS Downloads (GitHub Releases)](https://github.com/jacktdry/locwarp-macos/releases)** · [macOS guide](docs/MACOS.md) · [Report an issue](https://github.com/jacktdry/locwarp-macos/issues)

## Platform support

| | Maintained macOS fork | Original Windows version |
| --- | --- | --- |
| Downloads | [macOS Releases](https://github.com/jacktdry/locwarp-macos/releases) | [Upstream Releases](https://github.com/keezxc1223/locwarp/releases) |
| Computer | **Apple Silicon ARM64**, macOS 13+; Intel untested | Windows 10/11 x64 |
| Phone | iPhone/iPad; iOS 17+ is the main supported path | iPhone/iPad |
| USB | Apple pairing / RSD | Apple USB drivers |
| Wi-Fi | Apple native RSD, same LAN, paired device | Upstream Wi-Fi tunnel |
| Android | ❌ Not supported | ❌ Not supported |

**Validated:** iOS 27.0.1 native Wi-Fi on Apple Silicon, two simultaneous iPhone connections and teleportation, DVT location service, ⌘W window close and Dock reopen. Three-device operation, all iOS releases, Intel Macs and remote-network iPhone access remain unverified.

## macOS quick start

1. Get `LocWarp-*-mac-arm64.dmg` from [this fork's Releases](https://github.com/jacktdry/locwarp-macos/releases) for Apple Silicon only. The test build is not notarized.
2. Mount the DMG and move `LocWarp.app` to **Applications**. Do not turn off system protections to run an untrusted binary. Signed/notarized distribution is a separate future release gate.
3. Connect your iPhone in **Finder**, trust the computer on your iPhone, enable Developer Mode, and enable wireless pairing/syncing in Finder before using Wi-Fi.
4. Keep the Mac and iPhone on the same LAN. Open LocWarp, choose **Scan devices**, connect the paired iPhone, then use the map or route controls.
5. **⌘W** closes the window but leaves LocWarp running; reopen from the Dock. **⌘Q** quits and stops the backend.

If discovery fails, unlock the iPhone and check the Wi-Fi, Finder pairing and same-LAN connectivity. See [macOS setup and limitations](docs/MACOS.md) for details.

## Features

- GPS teleport and restoration of real location.
- Navigation, multi-stop routes and loops, random walk, joystick and speed control.
- Multi-device support: designed for up to three, validated with two iPhones on Mac Wi-Fi.
- Optional same-LAN mobile-control page with PIN pairing; desktop control APIs and WebSockets are local-only.

## Development and releases

- [macOS build, signing and validation](docs/MACOS.md)
- [Release and upstream sync policy](docs/RELEASING.md)
- [Original Windows guide (preserved)](docs/WINDOWS.en.md)
- [Original upstream project and Windows downloads](https://github.com/keezxc1223/locwarp)

`main` carries this fork's macOS product. Changes from upstream are merged through `sync/upstream-vX.Y.Z` and validated before they reach `main`.

## Attribution and license

Original LocWarp by [keezxc1223](https://github.com/keezxc1223). This community fork maintains macOS functionality and is **not an official upstream macOS release**. Licensed under [MIT](LICENSE), including the original copyright notice.

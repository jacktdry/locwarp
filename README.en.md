# LocWarp for macOS

<p align="right"><a href="README.md">繁體中文</a> · <b>English</b></p>

<p align="center"><img src="frontend/build/icon.png" alt="LocWarp" width="112"></p>

**Simulate iPhone and iPad locations over USB or Wi-Fi on macOS.** This is a community-maintained macOS fork of the [original LocWarp](https://github.com/keezxc1223/locwarp), preserving navigation and GPS simulation and adding Apple-native RSD transport and Apple Silicon packaging.

> **Release status: macOS ARM64 stable (v0.2.201).** Stable describes software functionality and validation, **not Apple security verification**. This build is **ad-hoc signed, without Apple Developer ID signing or notarization**. Gatekeeper may block installation; Intel Macs are unsupported. Apple has **not** verified this app.

**[macOS Downloads (GitHub Releases)](https://github.com/jacktdry/locwarp-macos/releases)** · [macOS guide](docs/MACOS.md) · [Report an issue](https://github.com/jacktdry/locwarp-macos/issues)

## Platform support

| | Maintained macOS fork | Original Windows version |
| --- | --- | --- |
| Downloads | [macOS Releases](https://github.com/jacktdry/locwarp-macos/releases) | [Upstream Releases](https://github.com/keezxc1223/locwarp/releases) |
| Computer | **Apple Silicon ARM64**, macOS 13+; **Intel not supported** | Windows 10/11 x64 |
| Phone | iPhone/iPad; iOS 17+ is the main supported path | iPhone/iPad |
| USB | Apple pairing / RSD | Apple USB drivers |
| Wi-Fi | Apple native RSD, same LAN, paired device | Upstream Wi-Fi tunnel |
| Android | ❌ Not supported | ❌ Not supported |

**Validated:** Apple Silicon and iOS 27.0.1 iPhones for USB/Wi-Fi connections, two-device GPS route continuation, Wi-Fi ↔ USB switching, real GPS restoration, Electron window close/reopen and idle-sleep prevention. Active-route GUI restoration was also integration-tested with **synthetic devices**, not live iPhone GPS. Literal ⌘W/⌘Q and Dock clicks have not been performed in hardware UAT. Three-phone setups, all iOS versions and iPad hardware remain incompletely verified; Intel Macs are unsupported.

## Install and first launch (Apple Silicon)

1. Open the **[v0.2.201 Stable Release](https://github.com/jacktdry/locwarp-macos/releases/tag/v0.2.201)** and download `LocWarp-0.2.201-mac-arm64.dmg`. **Apple Silicon M-series Macs only**; Intel Macs are not supported. Download only from this project's GitHub Releases.
2. **Double-click the DMG**, then drag **LocWarp.app into Applications**. Open LocWarp from **Finder → Applications**, **not directly from the mounted DMG**.
3. You may see a macOS warning about an unidentified developer or an app Apple cannot check for malicious software. This is an **ad-hoc signed, non-notarized build**. Only consider an app-specific security exception after checking that the download comes from a trustworthy source and has not been tampered with.

### If macOS blocks LocWarp: where is “Open Anyway”?

1. Try opening `LocWarp.app` from **Applications** once. If macOS blocks it, dismiss the warning.
2. Open **Apple menu  → System Settings → Privacy & Security**, then scroll down to **Security**.
3. Find the LocWarp warning and click **Open Anyway**; confirm **Open**, entering your Mac password if prompted. The button typically appears for about **one hour after the blocked launch attempt**. If it is absent, try launching LocWarp again first.
4. This creates an exception for **this app only**. **Do not disable Gatekeeper or SIP, or run Terminal commands that remove quarantine protections.** If the message instead says the app **“is damaged,” “will damage your computer,” or contains malware**, do **not** bypass the warning. Recheck the download or [report the problem](https://github.com/jacktdry/locwarp-macos/issues).

Apple documentation: [Open apps safely on your Mac](https://support.apple.com/en-ie/102445) / [Open an app by overriding security settings](https://support.apple.com/en-au/guide/mac-help/mh40617/mac). Running software that Apple has not notarized carries security risks.

## Connect an iPhone or iPad

**Initial USB pairing**

1. Connect the device to the Mac using a **data-capable USB/USB-C cable**. **Unlock the iPhone**, approve **Trust This Computer**, and make sure it appears in Finder's sidebar.
2. On iOS 16+, enable **Settings → Privacy & Security → Developer Mode**, reboot and confirm when prompted. If the toggle is missing, you may need compatible Xcode device preparation; a matching Developer Disk Image (DDI) may also need downloading or mounting.
3. Launch LocWarp, use the **USB scan/connect** control and select the paired device. Ensure the connection and location services are ready before simulating a location.

**Switch to Wi-Fi (USB-free after pairing)**

1. **Complete USB pairing first.** With the iPhone still plugged in, open **Finder → your iPhone → General**, select **“Show this [device] when on Wi-Fi”** and click **Apply**.
2. Disconnect the cable and connect the iPhone and Mac to the **same local network/Wi-Fi**. Keep the phone discoverable (unlock it for initial setup).
3. In LocWarp choose **macOS Wi-Fi connection → Scan devices**, then connect the paired device. This macOS mode **does not require administrator privileges**. VPNs, client isolation and firewalls may interfere with discovery.

Apple reference: [Enable Finder Wi-Fi discovery](https://support.apple.com/en-us/102471). USB and Wi-Fi have been tested with iPhones; iPad support is implemented architecturally but not fully validated on real hardware.

## Basic usage

1. **Teleport**: with a device connected, switch to **Teleport**, select a place on the map or enter coordinates, then apply the location change.
2. **Navigate**: choose **Navigate**, select the destination and movement speed, and start the route to simulate GPS movement.
3. **Multi-point Route**: add waypoints on the map, set speed and loop options, then start. You can save and reload routes.
4. **Stop is not Restore**: **Stop** stops the moving route, but the phone's simulated location may remain set. When finished, use **Restore** to clear simulated location and resume real GPS. For multiple devices, restore each device or use **Restore all**.
5. **Window lifecycle**: **⌘W** closes the window while the backend and running routes continue; reopen from the Dock to recover the route display. **⌘Q** quits. Closing the window does **not** stop GPS simulation.

**Connection issues?** Check that the phone is unlocked, the USB cable transfers data, Finder trust and Developer Mode are set, and the phone and Mac share the same Wi-Fi without isolation/VPN interference. Compatible Xcode/DDI may be needed when location services cannot initialize. See [macOS setup and limitations](docs/MACOS.md). Never expose the local control API (TCP 8777) to the public Internet.

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

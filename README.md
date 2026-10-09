# LocWarp for macOS

<p align="right"><a href="README.en.md">English</a> · <b>繁體中文</b></p>

<p align="center"><img src="frontend/build/icon.png" alt="LocWarp" width="112"></p>

**在 macOS 透過 USB 或 Wi-Fi 控制 iPhone／iPad 虛擬定位。** 本專案是 [LocWarp 原版](https://github.com/keezxc1223/locwarp) 的 macOS 維護分支；保留既有定位與路線功能，同時加入 Apple 原生 RSD 連線及 Apple Silicon 打包支援。

> **發行狀態：ARM64 測試版。** 目前 macOS 安裝檔僅使用 ad-hoc 簽章，**未經 Apple Developer ID 簽署或公證**，Gatekeeper 可能阻擋執行；Intel Mac 尚未實機驗證。不應把測試版視為已受 Apple 驗證的安全軟體。

**[下載 macOS 版本（GitHub Releases）](https://github.com/jacktdry/locwarp-macos/releases)** · [macOS 設定與限制](docs/MACOS.md) · [問題回報](https://github.com/jacktdry/locwarp-macos/issues)

## 平台與相容性

| 項目 | macOS 維護版 | Windows 原版 |
| --- | --- | --- |
| 取得版本 | [macOS Releases](https://github.com/jacktdry/locwarp-macos/releases) | [上游 Releases](https://github.com/keezxc1223/locwarp/releases) |
| 電腦 | **Apple Silicon ARM64**（macOS 13+）；Intel 待測 | Windows 10／11 x64 |
| 手機 | iPhone／iPad（iOS／iPadOS；iOS 17+ 為主要路徑） | iPhone／iPad |
| USB | Apple 配對及 RSD（需信任電腦） | Apple 裝置驅動／USB |
| Wi-Fi | macOS 原生 RSD（同一網路、先完成配對） | 上游 Wi-Fi Tunnel |
| Android | ❌ 不支援 | ❌ 不支援 |

**已驗證：** Apple Silicon Mac 上 iOS 27.0.1 iPhone Wi-Fi 連線、兩支 iPhone 同時連線與瞬移、DVT 定位服務、⌘W 關閉視窗與 Dock 重新開啟。尚未驗證所有 iOS 版本、三台同時操作、Intel 裝置或跨網路直接連線。

## macOS 快速開始

1. 從本倉庫的 [Releases](https://github.com/jacktdry/locwarp-macos/releases) 取得 `LocWarp-*-mac-arm64.dmg`（僅 Apple Silicon）。確認檔案來源；目前測試版尚未公證。
2. 掛載 DMG，把 `LocWarp.app` 移到 **Applications**。如 Gatekeeper 阻擋，請勿為了執行未受信任程式而關閉系統安全機制；正式版本須待 Developer ID 簽章／公證。
3. 在 Mac 的 **Finder** 連線 iPhone，於手機確認「信任這部電腦」，啟用「開發者模式」。初次無線連線前需在 Finder 啟用 Wi-Fi 同步／配對。
4. Mac 與 iPhone 連上同一個區域網路；開啟 LocWarp，使用「掃描裝置」選擇已配對的 iPhone，再操作地圖定位與路線功能。
5. **⌘W** 關閉視窗不結束背景服務，可從 Dock 重新開啟；**⌘Q** 才結束 App。

無法掃描時先確認 iPhone 已解鎖、與 Mac 在同一 Wi-Fi 網路及 Finder 配對仍有效。詳細限制／疑難排解見 [docs/MACOS.md](docs/MACOS.md)。

## 功能

- **瞬移**：直接設定 GPS 座標；可恢復真實定位。
- **路線**：導航、多點路徑、循環、隨機漫步、搖桿控制及速度調整。
- **多裝置**：架構最多三台；macOS 已以兩支 iPhone 實測。
- **手機操作頁**：同一 Wi-Fi 網路透過 PIN 配對，限定手機控制端點；桌面控制 API 與 WebSocket 不開放區域網路存取。

## 開發與發行

- [macOS 編譯、簽署與驗證](docs/MACOS.md)
- [Release 流程與上游同步](docs/RELEASING.md)
- [Windows 詳細手冊（保留原版內容）](docs/WINDOWS.md)
- [上游專案與 Windows 下載](https://github.com/keezxc1223/locwarp)

維護方式：本倉庫的 `main` 是 macOS 版本；透過 `upstream/main` 合併原作者的改動，先在 `sync/upstream-vX.Y.Z` 驗證，再整合到 `main`。Apple 原生定位功能會獨立維護，不要求上游改成支援 macOS。

## 授權與致謝

原始專案由 [keezxc1223](https://github.com/keezxc1223) 開發，這個 fork 延伸其 iOS 定位功能並維護 macOS 相容性。專案仍使用 [MIT License](LICENSE)，保留原始作者版權聲明；本 fork 非原作者的官方 macOS 發行版。

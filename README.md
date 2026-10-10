# LocWarp for macOS

<p align="right"><a href="README.en.md">English</a> · <b>繁體中文</b></p>

<p align="center"><img src="frontend/build/icon.png" alt="LocWarp" width="112"></p>

**在 macOS 透過 USB 或 Wi-Fi 控制 iPhone／iPad 虛擬定位。** 本專案是 [LocWarp 原版](https://github.com/keezxc1223/locwarp) 的 macOS 維護分支；保留既有定位與路線功能，同時加入 Apple 原生 RSD 連線及 Apple Silicon 打包支援。

> **發行狀態：ARM64 測試版。** 目前 macOS 安裝檔僅使用 ad-hoc 簽章，**未經 Apple Developer ID 簽署或公證**，Gatekeeper 可能阻擋執行；Intel Mac 不在支援範圍內。不應把測試版視為已受 Apple 驗證的安全軟體。

**[下載 macOS 版本（GitHub Releases）](https://github.com/jacktdry/locwarp-macos/releases)** · [macOS 設定與限制](docs/MACOS.md) · [問題回報](https://github.com/jacktdry/locwarp-macos/issues)

## 平台與相容性

| 項目 | macOS 維護版 | Windows 原版 |
| --- | --- | --- |
| 取得版本 | [macOS Releases](https://github.com/jacktdry/locwarp-macos/releases) | [上游 Releases](https://github.com/keezxc1223/locwarp/releases) |
| 電腦 | **Apple Silicon ARM64**（macOS 13+）；**Intel 不支援** | Windows 10／11 x64 |
| 手機 | iPhone／iPad（iOS／iPadOS；iOS 17+ 為主要路徑） | iPhone／iPad |
| USB | Apple 配對及 RSD（需信任電腦） | Apple 裝置驅動／USB |
| Wi-Fi | macOS 原生 RSD（同一網路、先完成配對） | 上游 Wi-Fi Tunnel |
| Android | ❌ 不支援 | ❌ 不支援 |

**已驗證：** Apple Silicon Mac 上 iOS 27.0.1 iPhone Wi-Fi 連線、兩支 iPhone 同時連線與瞬移、DVT 定位服務、⌘W 關閉視窗與 Dock 重新開啟。尚未驗證所有 iOS 版本、三台同時操作或跨網路直接連線；Intel Mac 不在維護範圍內。

## 安裝與首次開啟（Apple Silicon）

1. 前往 **[v0.2.200-macos.1 Release](https://github.com/jacktdry/locwarp-macos/releases/tag/v0.2.200-macos.1)**，下載 `LocWarp-0.2.200-macos.1-mac-arm64.dmg`。**僅支援 M 系列晶片的 Mac**，Intel 不支援；請只從本專案的 GitHub Release 取得檔案。
2. 在「下載項目」中**連按兩下 DMG**，打開磁碟映像檔，將 **LocWarp.app 拖進「應用程式（Applications）」** 資料夾。之後從 Finder 的「應用程式」開啟 LocWarp，**不要直接從 DMG 執行**。
3. 第一次開啟可能看到「無法驗證開發者」或「Apple 無法驗證是否含有惡意軟體」等提示。這版採 **ad-hoc 簽章，未經 Apple 公證**。只有在你已確認下載來源可信、檔案未遭竄改時，才考慮下方的單一 App 例外開啟方法。

### macOS 封鎖 LocWarp，該在哪裡打開？

1. 先從「應用程式」開啟一次 `LocWarp.app`，出現封鎖警告時選擇「完成」或關閉警告。
2. 開啟 **蘋果選單  → 系統設定 → 隱私權與安全性**，往下捲至「安全性」區域。
3. 找到關於 **LocWarp** 的封鎖訊息，按 **「強制打開」（Open Anyway）**；再次確認「打開」，必要時輸入 Mac 登入密碼。macOS 通常只在嘗試開啟後約 **一小時內**顯示此按鈕；找不到時可重新嘗試從「應用程式」開啟一次。
4. 這只會為**該 App 建立例外**，往後通常可以正常連按兩下開啟。**不要關閉 Gatekeeper／SIP、不要執行移除隔離標記的終端機指令。** 若警告顯示 App **已損壞**、**含有惡意軟體**或「**會損壞你的電腦**」，請不要強行執行，應停止使用並重新檢查下載來源或[提出 Issue](https://github.com/jacktdry/locwarp-macos/issues)。

參考 Apple 官方：[在 Mac 上安全地開啟 App](https://support.apple.com/zh-tw/102445)／[覆蓋安全性設定來打開 App](https://support.apple.com/zh-tw/guide/mac-help/mh40617/27/mac/27)。執行未經公證的軟體本身存在風險，請自行確認來源與完整性。

## 連接 iPhone／iPad

**第一次配對（USB）**

1. 使用可傳輸資料的 USB／USB-C 線連接手機與 Mac，**解鎖 iPhone**。在手機提示「信任這部電腦」時按「信任」，並確認 Finder 左側可以看到該裝置。
2. iOS 16+ 請至手機 **設定 → 隱私權與安全性 → 開發者模式** 開啟，依提示重新啟動並再次確認。若找不到選項，可能需要先用相容的 Xcode 完成裝置準備；裝置開發者磁碟映像（DDI）也可能需要下載／掛載。
3. 開啟 LocWarp，使用裝置區的 **USB 掃描／連接**功能，選擇已配對的 iPhone。確認顯示連線成功且定位服務可用，再開始操作。

**改用 Wi-Fi（無需長時間插線）**

1. **先完成上面的 USB 配對**。iPhone 插著線時，在 Mac 的 **Finder → 選擇 iPhone →「一般」** 勾選 **「連接 Wi-Fi 時顯示此 [裝置]」**，按 **「套用」**。
2. 拔下線，讓 Mac 與 iPhone 連上**相同的區域網路／Wi-Fi**，並保持 iPhone 可供發現（首次連線建議先解鎖）。
3. 在 LocWarp 的 **「macOS Wi-Fi 連線」→「掃描裝置」** 搜尋並連接已配對手機。macOS 此流程**不需以管理員身分執行**；VPN、網路隔離或防火牆可能影響偵測。

Apple 參考：[使用 Finder 設定 Wi-Fi 連線](https://support.apple.com/zh-tw/102471)。USB 與 Wi-Fi 皆以 iPhone 實測；iPad 具有相容架構，但尚未完成完整實機驗證。

## 基本操作

1. **瞬間移動**：連接手機後切換到「瞬間移動」模式，在地圖選擇目的地／使用座標，執行定位變更。
2. **導航移動**：切換「導航移動」，指定目的地並設定移動速度，啟動後 GPS 會沿路線更新。
3. **多點路徑**：切換「多點路徑」，在地圖加入途經點並設定速度、循環選項，再按開始；可從路線清單載入或儲存路徑。
4. **停止與還原不同**：「停止」只停止模擬移動，虛擬定位可能仍留在 iPhone 上。用完請按 **「一鍵還原」（Restore）** 清除虛擬定位、恢復真實 GPS；多裝置時逐台確認或使用「全部還原」。
5. **視窗與背景運作**：**⌘W** 只關閉視窗，後端及正在執行的路線仍會繼續；按 Dock 圖示重新開啟即可恢復畫面。**⌘Q** 才結束 App。不要把關窗當成停止定位的方法。

**連線失敗？** 請先檢查手機已解鎖、USB 線可傳資料、Finder 信任與開發者模式、同一 Wi-Fi，以及是否有 VPN／網路隔離。若定位服務無法啟動，可能需要相容的 Xcode／DDI。進一步細節見 [macOS 設定與限制](docs/MACOS.md)。切勿將本機控制 API（TCP 8777）公開到 Internet。

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

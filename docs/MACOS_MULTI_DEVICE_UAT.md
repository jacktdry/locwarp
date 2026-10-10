# macOS 多裝置與 native Wi-Fi 恢復 UAT（實機紀錄與待辦）

本文件是 `feature/macos-connection-resilience` 的人工驗收計畫，連線改善基線為
`61e4450`。2026-10-10 已完成隔離 ARM64 建置、後端 82、Electron 24 項測試、
前端 build、封裝後端 self-test 與 ad-hoc 嚴格簽章驗證，
實機通過範圍與剩餘未執行項目以本文件下方逐項紀錄為準，
不可將部分成功解釋為所有裝置、睡眠與 GPS 恢復均已驗收。
未另行記錄結果的案例預設 **NOT RUN**，由負責人安排時間與裝置所有人同意後執行；
此文件不要求立即操作。ARM64 封裝命令見 [MACOS.md](MACOS.md#獨立-arm64-uat-建置已驗證)。

## 2026-10-10 實機紀錄：Wi-Fi 純連線（部分通過）

本次在 Apple Silicon macOS 27.0.1 上使用隔離驗收後端
`frontend/release/uat-61e4450/mac-arm64/LocWarp.app/Contents/Resources/backend/locwarp-backend`
（Git 基線 `9c451d2`），不開 GUI、不進行 teleport／route／GPS 指令。
兩台已配對的實體 **iPhone 15 Pro、iOS 27.0.1**（匿名 A、B）皆由 Network
候選完成 macOS native Wi-Fi RSD 與引擎建立，兩個引擎均為 `idle`、
`current_position=None`。A 的 personalized DDI 已掛載；**B 的 DDI 未掛載**，
其 GPS/DVT 真正可用性仍 **BLOCKED**，不能僅依連線成功判定 PASS。

第二次啟動的測試後端連續觀察 60 筆、每 10 秒 1 筆（12:05–12:16，
約 10 分鐘）：**60/60 雙引擎存在、Idle、無虛擬定位；0 筆 API 錯誤／
逾時；11/11 次裝置清單確認 A、B 同時為已連線 Network**。
API snapshot 平均 54.9 ms、最長 335.2 ms；CPU 最高 2.4%；
RSS 首末 36.8→39.3 MB（期間有短暫波動）、描述符 18→18，
未見持續成長。僅能判定「雙裝置 Wi-Fi **連線註冊與被動 API 觀察** PASS」；
無 DVT/GPS 寫入驗證、睡眠、拔線、主從恢復或使用者手動斷線測試。
原始去識別證據僅存測試 Mac 的
`/tmp/locwarp-wifi-uat-20261010-phase2.jsonl`，未提交任何 UDID／座標。

首次啟動的命令工作階段因**測試工具執行上限**被結束，非可歸因於 LocWarp
自身的連線崩潰；因此改用延長時限的工作階段重新完成前述連續觀察。
最後在兩個引擎仍為 Idle、無模擬座標時，僅針對已核實 PID 的驗收後端
終止程序；確認 8777 listener 消失、`~/.locwarp/settings.json` 與事前備份
SHA-256 相同、正式安裝 App 未被取代。這次沒有發佈或推送。

**先前清理風險的複查結論（2026-10-10）：**
`DeviceManager._close_connection_handles()` 確實會呼叫
`location_service.clear()`，但 `DvtLocationService.clear()` 和
`LegacyLocationService.clear()` 都會先檢查 `_active`；從未開始模擬時
直接返回，不會初始化 DVT instrument 或傳送 GPS 清除指令。
已新增 `backend/tests/test_idle_location_cleanup.py`，以完全模擬傳輸驗證
閒置 DVT、已初始化但閒置 DVT、閒置 Legacy 都不會呼叫底層 GPS `clear()`，
且曾啟動模擬的 DVT 仍能正常清除，4/4 測試通過。**原先認為所有斷線都會
送出 GPS 清除指令是錯誤判斷，已更正；無需變更現有定位清理邏輯。**
本次 Wi-Fi 持續觀察仍未執行實機手動斷線或正常 shutdown，這兩項
仍屬 NOT RUN，不能以模擬測試代替實機結果。

**B 的 USB/DDI 後續確認（2026-10-10）：**
更換 USB-C 資料線後，`pymobiledevice3.usbmux` 已將 B（zih）列為 `USB`；
Xcode `devicectl device info ddiServices` 回報內容相容且可用，
`pymobiledevice3 mounter list --udid <B>` 進一步確認 Personalized
DeveloperDiskImage 的 `IsMounted=true`、`MountPath=/System/Developer`。
**不需要再下載／重掛 DDI**。先前的 DDI 未掛載是舊 Wi-Fi 工作階段的
觀察，不能推定目前仍缺失；但仍須在後續 Wi-Fi/USB 實機 GPS UAT
重新確認 DVT 工作，未獲 GPS 授權不發送定位操作。

**B USB + A Wi-Fi 混合連線實機驗收（2026-10-10，無 GPS 操作）：**
使用同一隔離 ARM64 驗收後端（來源 baseline `9c451d2`；其後僅增加回歸測試與文件）。
USB watchdog 偵測 B 並建立 USB 連線；隨後由 `/api/device/{udid}/connect`
明確連接 A 的 Network 原生 Wi-Fi 通道。兩台 iPhone 15 Pro 同時連線，
兩個 simulation engine 均為 Idle、`current_position=None`，此混合連線案例 **PASS**。
手動 `DELETE /api/device/{B}/connect` 成功（約 0.04 秒），A 維持已連線且
為唯一存活引擎；在其後 2 秒、再過 6 秒各一次觀察，B 均保持手動斷線抑制，
A 持續連線。再明確 `POST /api/device/{B}/connect`，B 約 3.1 秒恢復 USB，
A 未受到影響，雙引擎仍 Idle、無模擬座標。
驗收結束前確認兩台仍 Idle、無模擬座標，對已核實的測試後端程序送 SIGTERM
執行**正常關閉**，程序退出且 8777 listener 已釋放。
因此「混合連線」、「B 手動斷線抑制」、「B 明確重新連線」、「無模擬定位的正常關閉」
在本次環境 **PASS**；**截至本階段**，USB 實體拔插熱切換、GPS 實際寫入與
路線恢復仍 NOT RUN。先前 Wi-Fi-only 工作階段未做的項目並未被追認；
實體拔線自動接續的後續驗收結果另見下段。

**B USB → Wi-Fi 實際拔線自動接續（2026-10-10，PASS，無 GPS 操作）：**
原本的測試組合為 A（Wei's iPhone）Network Wi-Fi、B（zih）USB，皆已連線，
兩個 simulation engine 均 Idle、`current_position=None`。僅透過
`/api/device/{B}/auto-connect` 將 **B 單獨核准**；A 未加入核准清單。
先備份 `~/.locwarp/settings.json` 至權限 0600 的暫存檔，
並確認 B 有已認證且正在廣播的 macOS native Wi-Fi 配對記錄。

使用者實際拔除 **B 的 USB-C 資料線**，觀察得到：USB 通道約
**12:34:42** 關閉，USB watchdog 約 **12:34:44** 清除 B 的舊連線，
約 **12:34:55** 透過 macOS NativeRemotedTunnel 重新建立 B 的 Wi-Fi 連線，
從原 USB 中斷至成功約 **13 秒**（觀測精度受記錄時間與輪詢影響）。
期間 A 一直維持 Network 已連線；B 的 `is_connected` 曾短暫為 false，
隨後變為 true、connection_type=Network；兩個引擎回到 Idle、未設定模擬位置。
驗收監測器在 B 恢復後連續五次確認雙裝置在線，並滿足至少 25 秒的
恢復後穩定條件，結果 **PASS**。監測紀錄僅留在本機
`/tmp/locwarp-uat-usb-wifi-handoff-20261010.jsonl`（不提交裝置 UDID）。

測試後已停用 B 的自動連線，確認核准清單為空，
`~/.locwarp/settings.json` 與測試前備份 SHA-256 完全相符。
在全部引擎 Idle、無模擬位置時正常 SIGTERM 結束僅供驗收的後端，
驗證程序已退出且 8777 已釋放；既有正式安裝 App 不受影響。
此結果只驗證 **Idle 狀態的 USB → Wi-Fi 自動接續**：
GPS 寫入中途的 route/snapshot 精準接續、手機睡眠及重新插 USB 的反向
Wi-Fi → USB 優先切換仍為 **NOT RUN**，不能宣稱已通過。

**B 主裝置進行中路線 → A 接手 → B Wi-Fi 回歸（2026-10-10，PASS）：**
本案例獲兩台 iPhone 的 GPS 模擬測試授權後執行；在 Apple Silicon Mac
的隔離 ARM64 驗收後端進行，不啟動 GUI、不安裝或覆蓋正式版 App。
測試前備份 `~/.locwarp/settings.json`（檔案權限 0600），建立 6 分鐘
失聯逾時安全保護，確保超時可嘗試還原兩台裝置。先讓 B（zih）USB
成為 primary，透過 `/api/location/teleport` 設定短距離起點，接著以
`/api/location/loop` 執行**約 30 公尺邊長的 4 點閉合路線、步行 3.2 km/h**；
觀察到 B 的狀態為 `looping`、行進距離持續增加。僅將 A、B 加入此輪
Auto-connect 核准清單，A 從 native Wi-Fi 加入，成為 B 的位置 follower。
拔線前 3 筆同步取樣，A／B 虛擬定位差距皆為 **0 公尺**，B 持續行進。

使用者隨後實際拔除 B 的 USB-C 線。獨立 read-only 監測器記錄到：

- 監測開始後 **24.0 秒**：B USB 裝置消失。
- **28.6 秒**：primary 轉為 A，A 狀態為 `looping`，B 原引擎已移除；
  A 自此能繼續移動，而非僅保持原位置。
- **30.1 秒**：B 暫時未連線，Wi-Fi 候選可見；A 一直維持 Network 已連線。
- **35.7 秒**：B 經 native Wi-Fi 重新連接，取得模擬位置，開始跟隨 A。
- B 回歸後連續 **7 筆**雙機連線且有位置的監測取樣，約 **17.3 秒**；
  A、B 回報模擬位置差距在 **0～0.9 公尺**之間。
- A 接手後的 `looping` 樣本中，`distance_traveled` 有 **20.4 公尺**的
  區間變動，證明引擎持續推進。該欄位會於新一圈重置，不能拿
  首筆與末筆當成單調累積里程；本測試只證實持續移動及主從接續，
  不宣稱證明每一個細分路段百分之百無跳點。
- **19 筆**監測紀錄、**0** 讀取異常；原始含裝置 ID／測試座標的觀測檔
  僅留在本機 `/tmp/locwarp-gps-live-handoff-20261010.jsonl`，未提交 Git。

**恢復真實 GPS：** 完成觀測後立即對 A、B 分別呼叫
`POST /api/location/restore?udid=…`，兩者均回應 `restored`，
引擎變為 `idle`；關閉兩台 Auto-connect 核准後，正常 SIGTERM
結束已確認身分的驗收後端，8777 listener 釋放。隨後使用 Apple
`devicectl device simulate location clear --device …` 作第二道獨立復原，
**兩台均回報 `Cleared location simulation` 且 exit code 0**。
已解除逾時保護。測試期間僅設定檔的 `last_position` 曾變更，
核對其他欄位一致後，已將這一項還原為測試前狀態，最終設定檔與
事前備份 **SHA-256 完全一致**、Auto-connect 核准清單為空。

結果：**本次雙機活動路線主從故障切換／B 回歸位置同步 PASS**。
限制：無獨立第三方 App 的定位讀值錄影，精細路段連續性只能依照
後端 snapshot 與模擬座標比較；雙機 GPS 清除獲 API 與 Apple 原生命令
雙重成功回報，但未實際拿手機上的地圖 App 人工目視定位點。
**手機睡眠／喚醒、Wi-Fi → USB 反向切換、第三／第四台裝置，及正式版 GUI
仍 NOT RUN**，不可將此案例擴大為整個 milestone 完成。

**Wi-Fi → USB 優先切回：待實機 UAT 的守護式修正（2026-10-10）：**
先前 USB watchdog 對已透過 Network 連線的同一 UDID，在新 USB 出現時
呼叫 `DeviceManager.connect()`，卻因為該 UDID 已存在而直接返回；原本的
Network handle 不會轉為 USB，甚至可能誤發 `device_connected: USB`。
現在 `DeviceManager.upgrade_native_wifi_to_usb()` 先準備並驗證新的 USB
RSD/DVT，成功後才切換單一裝置的連線／引擎，再釋放舊 Wi-Fi handle；
USB 握手或引擎重建失敗則保留原 Network，不發假的成功通知。手動斷線
抑制與 Auto-connect 未核准者不會升級，也不會影響另一台已連線手機。
**安全限制**：僅 Mac、明確核准 Auto-connect、引擎完全 Idle、沒有保留
模擬座標且 location service 不處於 active 時才切換。正在導航／循環路線
或仍有虛擬 GPS 的裝置，**維持原 Wi-Fi，不搶佔 DVT 或清除模擬定位**；
不宣稱已支援「動態路線中自動 Wi-Fi → USB 無縫熱切換」。
全模擬回歸測試新增 `backend/tests/test_usb_upgrade.py`，包含成功切換、
USB/DVT 失敗保留 Wi-Fi、主從隔離、抑制／核准及活動定位守衛，
上述程式修正先完成 **mock 回歸驗證**；後續使用新版測試後端及實體
USB 資料線確認 `DeviceManager` 的**實際**連線類型與 DVT，結果見下段。

**B Wi-Fi → USB 反向切換實機驗收（2026-10-10，Idle，PASS）：**
先前一次準備（約 13:16）因使用者插線前測試窗口到期，由安全清理程序
正確停用 Auto-connect 並關閉後端；舊監測期間沒有 USB 插入事件，
**不得算作通過**。重新準備後確認 B 已拔除 USB，A 與 B 的 macOS
native Wi-Fi 配對均經過認證且可用。使用包含 `aef4225` 守護式
USB 升級修正的獨立 Python 測試後端（**非**上一版封裝二進位）
分別連接 A、B，兩者都是 `connection_type=Network`、已連線，兩個
engine 均為 `idle`、無模擬位置；備份原有使用者設定，只核准 B 自動連線。
在使用者確認 **實際插入 B USB-C** 之前，唯讀監測已啟動。

新監測捕捉到 B 實體 USB 由未出現轉為出現（觀測器時間起算約 41.7 秒），
B 的連線由 `Network` 真正改為 **`USB`、`is_connected=true`**，
而 A 持續為 `Network`、`is_connected=true`。兩個引擎全程維持
`idle`、`current_position=None`。監測記錄至少 **15 筆**成功升級後的
取樣、約 **65.6 秒**，無 API 讀取錯誤。測試後端的獨立 stderr 紀錄
進一步顯示 B 經 USB 握手成功、personalized DDI 已掛載，重新建立
simulation engine，並釋放 B 舊的 Wi-Fi handle；有
`Upgraded idle native Wi-Fi device ... to verified USB` 成功紀錄。
原 observer 的 `upgraded_log` 為 false，因它只掃描
`~/.locwarp/logs/backend.log` 的新增內容，並未讀到此次測試後端的
stderr 訊息；**以 stderr 的交接證據與 API 實際傳輸狀態為準**，
不可把該欄位誤解為未發生通道升級。原始觀測檔只存於測試 Mac：
`/tmp/locwarp-reverse-usb-uat-20261010-phase2.jsonl`（不提交 UDID）。

測試結束前再次核對 A Network、B USB、兩個 engine Idle／無模擬座標；
停用 B Auto-connect 並確認核准清單為空，SIGTERM 正常結束
**已核實身分**的測試後端、8777 釋放、唯讀監測程序關閉。
`~/.locwarp/settings.json` 與本輪事前備份的 SHA-256 **完全一致**，
逾時清理旗標已解除；正式安裝版未受影響。本案例驗收結果為
**Idle 狀態的真實 Wi-Fi → USB 反向切換 PASS**。
它不包含活動 GPS／導航時強制切換、手機休眠喚醒與正式 GUI 操作，
這些項目仍須各自驗證。

**A 手機螢幕鎖定／解鎖的被動觀察（2026-10-10，部分通過）：**
使用者依指示鎖定及解鎖 A，B 維持 USB；測試前備份設定，
僅暫時核准 A 自動連線。測試環境中 A 使用 native Wi-Fi、B 使用 USB，
兩個引擎均 Idle 且沒有模擬位置。
唯讀觀測取得 67 筆取樣，約 277.6 秒：A 全程顯示 Network／已連線，
B 全程顯示 USB／已連線；兩個引擎均 Idle、無模擬座標；0 API 錯誤。
RSS 38.2–49.7 MB、檔案描述符 26–28，僅屬短時間觀察。

**判定：鎖定／解鎖期間，API 回報的雙機連線狀態保持穩定。**
未進行鎖定後底層 DVT 獨立健康探測，因此不代表 Wi-Fi 定位通道
已通過實際操作驗證；此次亦未觀察到斷線，不能證明自動重連已發生。
鎖定／解鎖精確時間未獨立記錄，無法計算恢復延遲。
Mac 整機休眠／喚醒與正式 GUI 實際操作仍為 NOT RUN。

測試結束後已停用 A 自動連線、確認核准清單為空，正常結束
經過核實的驗收後端，釋放 8777 並關閉監測、解除逾時保護。
設定檔 SHA-256 與測試前備份完全相符，正式安裝版未受影響。
觀測原始資料只保留在測試 Mac 的
`/tmp/locwarp-lock-uat-20261010.jsonl`，不提交裝置識別資料。

同日測試：Electron `npm test` 24/24 通過（含關窗、Dock 重新開窗及
快照還原模擬測試），前端 `npm run build` 成功、後端 90/90 通過。
**這些測試不等於真實 Electron GUI 已完成驗收。**

## Read-only 前置與授權界線

先只讀確認分支／SHA、待測 App 路徑、簽章驗證紀錄、macOS／iOS 版本、
目前執行中的 LocWarp／後端與 8777 listener 的擁有者。不得啟動第二個後端、
殺掉不明程序、碰正在執行的路線，或修改 `/Applications/LocWarp.app`。
驗收 App 位於 `frontend/release/<subdir>/mac-arm64/LocWarp.app`；
同 bundle ID `com.locwarp.app`、8777 與 `~/.locwarp/`，正式版與驗收版不可並行。
輸出目錄隔離不會隔離使用者設定／日誌／配對紀錄。

在任何寫入或啟動前，先約定資料保留與還原方式；負責人獲同意後，才備份
`~/.locwarp/settings.json` 及需保留的資料（不存在也須記錄），再正常結束既有
LocWarp，確認其後端已退出且連接埠空閒。不變更 appId、不搬移已安裝 App。

- **被動觀察**：只讀既有設定、日誌、程序 metrics 與下述 GET API；
  不掃描、不連線、不切換 Auto-connect，不變更 GPS。若既有主裝置有模擬位置，
  新連線／重新連線也可能自動同步位置，不能當成被動觀察。
- **連線／環境階段**：啟動 App、信任／配對、Developer Mode、DDI 準備、
  Auto-connect 設定、連接／拔線、切換 Wi-Fi、休眠與重啟都需事前同意。
  先確認所有裝置無進行中模擬、主裝置沒有可被同步的模擬位置。
- **GPS 階段**：teleport、route、群組同步、恢復／重套模擬位置與還原定位，
  需各受影響裝置所有人明確同意。記錄裝置、座標、路線、開始／停止條件及
  還原方式；不得以連線同意推定 GPS 同意。未同意就標為 NOT RUN。

## 裝置與環境準備（獲同意後）

至少兩台實體 iPhone，代號 A／B；三台上限案例需要 C，第四台拒絕案例需要 D。
記錄個別 iOS 版本、可用傳輸與匿名 UDID 對照；不可把同一手機不同候選列當成兩台。
每台解鎖、啟用 Developer Mode（需要時重新啟動並確認）、在 Finder 與手機上
完成 trust，使用可傳資料的 USB 線，確認相容 DDI／定位服務準備狀態。
Wi-Fi 案例須先以 USB 配對並啟用 Finder「透過 Wi-Fi 顯示此 iPhone」，
Mac／手機使用可信任同一網路；記錄 VPN、防火牆、AP isolation 與本機網路權限。
設定缺失標為 BLOCKED，不全域停用安全設定、不移除配對紀錄、不啟動 root GUI。

避免並行 Xcode／devicectl／其他裝置工具干擾 Apple's remoted；
需要它們準備裝置時先結束該準備流程，再開始計時。
native pairing record、Network 候選或 `is_connected` 單一欄位都不是 GPS 成功證據。

## 被動證據與判定方法

在已核准且已啟動的驗收工作階段，可讀取：

```bash
curl --max-time 3 --fail --silent --show-error http://127.0.0.1:8777/api/device/list
curl --max-time 3 --fail --silent --show-error http://127.0.0.1:8777/api/device/auto-connect
curl --max-time 3 --fail --silent --show-error http://127.0.0.1:8777/api/location/snapshot
```

只使用 GET，不以 POST 連線或定位充當 probe。保留帶時間的
`~/.locwarp/logs/backend.log`（含輪替檔）與上述回應；分享前遮蔽 UDID、
座標、路線及配對資訊。記錄 App／後端 PID、CPU、RSS／記憶體、執行緒／
檔案描述符數、8777 listener 數及 API 延遲，可用「活動監視器」或針對已知 PID
的只讀程序工具；不假定存在專用 metrics API。

每案先穩定觀察 10 分鐘；中斷後從條件恢復（手機解鎖、網路／線路可用）開始計時，
最多等待 6 分鐘涵蓋最長 5 分鐘 backoff，再觀察 10 分鐘。每 10 秒記錄 GET
結果，timeout 上限 3 秒。這是人工驗收門檻，不是程式的 SLA。
PASS 須 API 無 timeout／5xx、目標狀態在期限內達成、未受影響裝置保持連線，
無 crash、重複裝置／後端、密集無界重試或定位誤套到別台。
恢復後 CPU 不得持續超過單核心 80% 達 60 秒；10 分鐘穩定期後再觀察 10 分鐘，
若 RSS 或描述符數連續增加且較穩定基準高出 20%，標 FAIL 並保留曲線供分析。
短暫尖峰也需記錄。缺裝置、權限或前提為 BLOCKED；未執行為 NOT RUN，均不可計為 PASS。

## 連線矩陣（每案獨立記錄）

此階段不設定模擬位置；只對已同意的 A／B 啟用 Auto-connect。
GPS 判定另見下一節。

| 案例 | 核准後的操作 | PASS 條件（另須符合共同門檻） |
| --- | --- | --- |
| USB 一台 | A 接 USB；拔插一次 | A 可連線與恢復；不得出現第二個 A 或額外後端 |
| USB 兩台 | A 穩定後接 B，再反向順序重測 | A／B 同時可用；B 失敗不拆掉 A；未能兩台同時連線須 FAIL／記錄 native 限制 |
| native Wi-Fi 一台 | 先完成配對，USB 全拔除，再啟動；A 離線後回到網路 | 實際 native 連線成功且恢復，不以 stale record 當成功 |
| native Wi-Fi 兩台 | A／B 無 USB 同時連線；輪流讓一台離線／回線 | 兩台同時穩定；另一台不被斷線、名稱／UDID 不混用 |
| USB → Wi-Fi | A 已核准且 USB 連線中拔線，B 維持 Wi-Fi；A 再插 USB | A 清理舊 handle 後恢復，無重複 engine；B 穩定。另對未核准裝置驗證不自動 fallback |
| 手動斷線抑制 | 手動 disconnect A；等待、掃描、關開 Auto-connect，再明確 connect A | 同一後端工作階段內不自動重連；掃描／toggle 不解除抑制；明確 connect 才恢復 |
| 休眠／喚醒 | A／B native Wi-Fi；Mac 休眠至少 2 分鐘再喚醒，另測手機鎖定／解鎖 | 喚醒後期限內恢復；兩台獨立、無 runaway retry；睡眠期間不要求 API 回應 |
| 關窗／重開 | 用 ⌘W 關閉，再由 Dock 重開 | 同一後端、同一連線狀態；視窗不新增後端 |
| 三台上限 | 加入 C；嘗試核准 D（如有第四台）；A／B／C 連線時另嘗試手動連線 D | 第四個核准及第四台連線均被拒絕，既有選擇／連線不變；無 D 則拒絕案例 BLOCKED，不能推算 PASS |
| 重啟持久化 | 記錄核准 A／B／C，正常 ⌘Q，確認退出再重開；另記錄未核准 D | 核准名單保留；僅可達、已核准者自動連線。手動抑制僅限前一工作階段，不要求跨重啟保留 |

三台上限包含 **Auto-connect 核准上限與連線上限**，不代表三台 userspace tunnel 可並行。
三台同時連線仍需另記錄 USB／native Wi-Fi 組合與實際結果。

## GPS、主從與恢復矩陣（須明確 GPS 同意）

以 A 為主、B 為從，使用已同意的測試座標與短路線。每案記錄
`snapshot` 的 primary、路線、進度、pause 狀態及兩台實際定位觀察；
僅 UI 地圖更新不足以 PASS。位置差容許值先約定並記錄，例如 20 公尺、
5 秒內收斂；未約定或無實際手機觀察則 BLOCKED。

| 案例 | 核准後的操作 | PASS 條件 |
| --- | --- | --- |
| Teleport／群組同步 | 分別操作單台及 A／B 群組到核准座標 | 受影響台符合選取範圍及容許值；未選取者定位不變 |
| 路線與從裝置恢復 | 群組 route 中讓 B native Wi-Fi 中斷後恢復 | A 持續路線；B 回到當下主裝置位置／跟隨，不重播路線起點 |
| 主裝置恢復 | A native Wi-Fi 短暫中斷；另測 A 確實離線並由 B 接替 | 短暫恢復保留可恢復進度／pause；確實離線時記錄 primary 交接，B 接續而非回起點；A 回來不錯套舊主狀態 |
| 暫停／停止邊界 | 暫停時中斷並恢復；另測停止後恢復 | pause 不自行變 running；已停止路線不復活、不重套過期位置 |
| USB → Wi-Fi／休眠 | 在核准路線中重做傳輸切換與喚醒 | 進度／主從身份可解釋、無未核准 teleport；清楚記錄中斷時間與恢復誤差 |
| 後端重啟 | 先停止並還原 GPS，再正常退出／重開 | 核准名單保留；不把存活中的路線跨後端重啟當保證，無未授權模擬自動開始 |

每個恢復案再測一次於無 GPS 模擬的位置，確認不憑連線自行建立模擬。
任何意外位置變更立即 FAIL、停止新增動作並依已同意方式還原。

## userspace singleton 風險

pymobiledevice3 USB userspace tunnel 是程序級 singleton：第一台 iOS 17+ USB
通常持有 PreferredRsdTunnel，包含 handshake 期間；第二台走有界 no-root native
嘗試，不保證該 macOS／iOS 組合可用。native 失敗應留下原連線且有 backoff；
不能以另開 userspace tunnel、root TUN 或重啟所有手機迴避測試。
native Wi-Fi／iOS 16 legacy 不占此 userspace slot，但仍需實機證據。
兩台 USB 測試尤其要記錄實際 transport、slot 釋放與 A／B 順序；
Apple remoted 與其他工具競爭也可能造成會話被取代。穩定性與 GPS 能力分別判定。

## 清理、還原與交接

經同意停止所有路線／跟隨，逐台使用還原真實定位動作並由所有人確認結果；
失敗就保留 FAIL 與待處理事項，不宣稱已還原。恢復原 Auto-connect 選擇，
正常 ⌘Q 退出驗收 App，確認其後端／子程序與 8777 listener 消失。
只清理驗收擁有的程序，不能殺不明 listener。關閉自己開的觀察工具。
若需還原備份設定，先確認兩版都已退出再由負責人執行；
不要回寫整份舊資料蓋掉期間的新路線或使用者資料，不刪系統 pairing records。
記錄 Wi-Fi／Developer Mode／配對設定哪些經同意保留、哪些需所有人自行還原。
已安裝正式 App 保持原位；待所有人確認清理後，才另行決定是否啟動正式版。

每案交接欄位：日期、測試人／同意範圍、SHA、建置／簽章紀錄、App 路徑、
Mac／iOS 版本、裝置代號／transport、步驟與時間、預期／實際、API／日誌／
metrics 證據、PASS／FAIL／BLOCKED／NOT RUN、還原結果與剩餘風險。
雙 iPhone PASS 不代表三台、不同 iOS、Developer ID／notarization 或發布驗收通過。

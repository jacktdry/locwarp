# macOS 多裝置與 native Wi-Fi 恢復 UAT（待執行）

本文件是 `feature/macos-connection-resilience` 的人工驗收計畫，連線改善基線為
`61e4450`。2026-10-10 已完成隔離 ARM64 建置、後端 78、Electron 24 項測試、
前端 build、封裝後端 self-test 與 ad-hoc 嚴格簽章驗證，
但不代表多裝置、休眠或 GPS 恢復已通過實機驗收。
所有案例預設 **NOT RUN**，由負責人安排時間與裝置所有人同意後執行；
此文件不要求立即操作。ARM64 封裝命令見 [MACOS.md](MACOS.md#獨立-arm64-uat-建置已驗證)。

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

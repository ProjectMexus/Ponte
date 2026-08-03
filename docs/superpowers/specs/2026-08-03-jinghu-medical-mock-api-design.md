# 鏡湖通醫療 Mock API 設計說明

## 目的

為 Ponte Demo 建立一組只供本地展示使用的鏡湖通醫療 Mock API 文檔，讓 Workflow Orchestrator 可以模擬門診掛號、檢查／治療預約及查詢個人預約。API 採用 FHIR-inspired JSON，但不宣稱是鏡湖醫院正式 API，也不接觸真實病歷或醫療資料。

## 設計決策

1. 文檔以繁體中文 Markdown 交付，放在 `docs/api/jinghu-medical-mock-api.md`，方便前後端、MCP Adapter 及 Demo UI 共同閱讀。
2. API 根路徑固定為 `/mock/medical`。
3. 將「網上掛號」與「檢查／治療預約」拆成兩種預約類型，但使用共同的 `Appointment` 資源，便於「我的預約」統一查詢。
4. 以 `X-Patient-Id` 表示已登入的 mock 就診人，以 `Idempotency-Key` 防止提交重試造成重複掛號。
5. 時段查詢、掛號及預約均返回可供 UI 顯示的科室、醫生、地點、日期、時間及剩餘名額。
6. 所有建立操作都返回 `Task` 摘要，與 Arch 文件中的 Durable Task、Action Receipt 及 MCP Tool Adapter 方向對齊。

## 功能範圍

- 查詢科室及醫生。
- 查詢指定科室的門診掛號時段。
- 建立門診掛號。
- 查詢檢查／治療服務及可用時段。
- 建立檢查／治療預約。
- 查詢我的預約清單及單筆預約詳情。
- 查詢提交任務狀態。
- 統一錯誤格式、狀態列舉、分頁及 mock 業務規則。

## 非目標

- 不實作真實登入、OAuth、病歷讀取、支付或臨床決策。
- 不提供診斷、用藥建議或醫療判斷。
- 不模擬完整 FHIR Server。
- 不在本次文檔加入取消、改期或家屬代理流程；這些能力可沿用 Arch 文件中的 `reschedule_appointment` 方向另行擴展。

## 參考依據

鏡湖通首頁目前將「網上掛號」、「檢查／治療預約」及「我的」列為獨立功能入口；鏡湖醫院公開門診說明亦提到網上預約掛號以科室／醫生／日期／時段為主要選擇，並有預約期限及報到要求。本設計只借用這些使用流程概念，所有資料和規則均為 Ponte Demo 的合理 mock 值。

## 驗收條件

- `docs/api/jinghu-medical-mock-api.md` 存在且可單獨閱讀。
- 文檔明確描述三條核心流程：不同科室掛號、檢查／治療預約、我的預約查詢。
- 每個核心 endpoint 均有方法、路徑、輸入欄位、成功輸出及錯誤情況。
- JSON 範例內的欄位名稱、狀態值及資源關係一致。
- 文檔標明 mock、FHIR-inspired、身份及私隱限制，避免被誤當成正式醫療 API。

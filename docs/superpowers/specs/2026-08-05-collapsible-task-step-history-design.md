# Task 步驟歷史收合設計

## 目標

讓服務工作區的流程步驟在完成或處理完後自動收合，同時保留該次步驟的內容供使用者回看。正在進行或需要使用者處理的步驟預設展開；重試產生的同名步驟各自保留，不合併成一筆。

## 核准方案

採用前端 task-level step history snapshot，不修改 middleware response contract：

- `response.steps` 的每一個出現次數視為一筆獨立步驟歷史，例如兩次 `create_appointment` 會顯示成兩筆。
- 前端第一次看見某個步驟出現時，保存當時的 `data`、`error`、`recovery` 和助手訊息 snapshot。
- 步驟狀態顯示沿用現有 `status`／`ok`／`current_step` 推導規則。
- 已完成或已處理的步驟使用原生 `<details>`，預設 `open=false`；目前步驟和目前需要 recovery 的步驟預設展開。
- 使用者手動展開或收合後，重新渲染 task card 不會重置該步驟的選擇；當步驟由活動狀態轉成已處理狀態時，才執行一次自動收合。

## 方案比較

### 方案 A：前端保存步驟 snapshot（採用）

在現有 task record 加入 `stepHistory`，以 `step_id + occurrence` 識別每次步驟出現。優點是不用改 API、能保留 retry 的重複步驟，風險和變更範圍最小；snapshot 內容受現有 user-safe renderer 控制。

### 方案 B：middleware 新增 step detail history

由 backend 為每個 step 回傳完整 detail 與識別值。資料語意最完整，但需要改 SessionState、response contract、middleware tests 和前端相容邏輯，超出目前只需要 UI 行為的範圍。

### 方案 C：只用目前 response.data 重建步驟內容

不保存歷史，每次 render 都以最新資料填滿所有步驟。實作最少，但 retry 前後的資料會混在一起，無法滿足「查看當時細節」。

## UI 行為

每個步驟仍以清晰的中文名稱、序號／完成勾號和狀態顯示。步驟 row 內加入可鍵盤操作的 `<details>`：

- 已完成：顯示勾號、名稱和「已完成」，預設收合；點擊標題可展開當次摘要。
- 目前進行：預設展開，顯示當時安全資料摘要。
- 需要處理：如果是目前 recovery 步驟則預設展開，顯示錯誤／下一步；已經離開目前流程的舊失敗步驟預設收合。
- 重試：每個 occurrence 保留自己的序號、狀態與 snapshot，不把同名步驟去重。
- 空的步驟摘要顯示簡短的「這一步沒有其他資料」，不顯示 raw JSON、tool name、request ID 或內部 ID。

外層 task card 的既有收合行為不變：新任務及活動中的 task 展開，終止 task 收合但仍可重新展開；步驟 details 的互動狀態獨立保存。

## 資料流與實作邊界

`updateTask(taskId, response)` 會：

1. 將 response.steps 按出現次數對應到 task.stepHistory。
2. 新 occurrence 建立 snapshot；既有 occurrence 保留 snapshot 和使用者的 expanded 狀態。
3. 狀態由既有規則推導，活動狀態轉為已完成／失敗時將 expanded 設為 false。
4. renderTaskList 使用 stepHistory，而不是直接使用 response.steps。

步驟摘要使用既有 `renderMedicalData`、`renderFriendlyData`、`renderRecovery` 和錯誤文字渲染，並按 step ID 選取當時相關資料：查詢預約顯示 appointments，載入服務顯示 services，搜尋時段顯示 slots，選擇／確認／提交／完成預約顯示 selected slot。這些資料仍經既有白名單和本地化映射，不向使用者暴露 backend 內部欄位。

不新增 browser storage、backend history API、新的 action payload 或 middleware state 欄位。頁面重新載入後沿用現有 session 行為。

## 錯誤處理與相容性

- 缺少或格式不完整的 `steps` 視為空列表，不阻止 task card 其餘資料渲染。
- `data`、`error`、`recovery` 只保存 JSON-safe snapshot；renderer 仍以 textContent 和既有 safe-field mapping 顯示。
- 沒有歷史資料的舊 task record 仍可由目前 response.steps 正常建立 stepHistory。
- ARIA label、原生 details 鍵盤操作、大字體、focus-visible 和手機版 layout 必須保留。

## 驗證

1. static contract test 確認 stepHistory、occurrence、step details snapshot、auto-collapse 和 user toggle markers 存在。
2. `node --check` 檢查全部 frontend JavaScript。
3. `python -m unittest tests.test_frontend_static -v` 通過。
4. 手動／smoke 檢查醫療預約流程：已完成步驟預設收合；目前／recovery 步驟展開；重試後同名步驟各自保留，展開舊步驟可看到其當時摘要；task card 外層收合行為沒有回歸。

## 非目標

- 不改變 middleware 或 mock backend 的 steps、tool events 和資料格式。
- 不新增完整的永久步驟歷史或跨頁保存。
- 不提供 raw technical detail inspector。

# 醫療預約 recovery 與任務歷史 UI 修正設計

## 目標

修正醫療預約流程中的三項行為：

1. 預約衝突時，任務卡只顯示一份衝突說明、預約摘要和操作選項。
2. 完成預約時，任務卡只顯示一份完成摘要；歷史子任務卡仍保留當時的可用選項和使用者所選 action，點開已完成任務時預設展開最後的「完成預約」步驟。
3. 預約衝突後不把替代方案固定成超聲波，而是讓使用者重新選擇當時可用的服務／科室和日期。

實作分支：`codex/fix-appointment-ui-recovery`。

## 根因

`frontend/interaction-view.js` 同時渲染兩個內容來源：

- `stepHistory` 的 snapshot 會渲染助手訊息、`selected_slot` 摘要和 recovery。
- task card 主內容又用最新 response 再渲染一次 `selected_slot`、錯誤和 recovery。

因此 `DUPLICATE_BOOKING` 和已完成預約會出現重複摘要。衝突說明又同時存在於助手訊息和 recovery explanation，造成同一句話在同一個步驟內再次出現。

目前 `middleware/task_manager/recovery.py` 對 `DUPLICATE_BOOKING` 會從已載入服務逐一生成 `search_slots` action。當服務資料只有一個其他服務時，畫面便會看起來固定提供超聲波；這個 action 也會直接沿用舊服務清單和舊日期，不能讓使用者重新選擇完整方案。

## 方案

採用「最新步驟擁有已處理內容 + 通用重新選擇服務 action」的方案：

- 保留既有 task/step response contract，不建立第二套前端流程。
- `DUPLICATE_BOOKING` recovery 改為提供 `select_service` 通用 action，並保留 `cancel` 和既有 `human_help` 選項。
- middleware 收到 `select_service` 後重新呼叫 `medical.list_appointment_services`，清除舊服務／時段選擇，回到 `selecting_service`。
- 前端在 `selecting_service` 狀態展示最新動態服務清單、日期範圍和取消 action，不從 recovery payload 讀取固定服務 ID。
- terminal 或 recovery response 的摘要、錯誤和說明以最後一個 step snapshot 為唯一可見來源；task card 主內容只在歷史沒有相同內容時才渲染。
- task-level action buttons 仍是唯一可互動的 action controls。歷史子任務卡只顯示當時選項和使用者所選 action 的唯讀紀錄，避免出現第二組可提交按鈕。

相比只用 CSS／前端隱藏重複內容，這個方案同時修正 recovery action 的語意；相比新增 middleware 的永久 step-history contract，變更集中在現有 response 與前端 task record，風險較小。

## 元件與資料流

### 衝突 recovery

1. `medical.create_appointment` 返回 `DUPLICATE_BOOKING`。
2. `TaskManager` 建立 recovery plan，options 為：
   - `select_service`：`重新選擇其他服務／科室`，payload 為空物件。
   - `cancel`：取消這次預約。
   - `human_help`：轉接人工協助。
3. 前端只顯示一份 recovery explanation 和一組 action buttons。
4. 使用者按 `select_service` 後，controller：
   - 清除 `service_id`、`date_from`、`date_to`、`slots`、`slot_id`、`selected_slot`、`task_id` 和 `task_status` 等舊選擇；
   - 重新呼叫 `medical.list_appointment_services`；
   - 保存新的 `services`；
   - 將 task 轉為 `selecting_service` / `select_service`；
   - 返回一個可重新選擇的動態服務清單，並附取消 action。
5. 使用者選擇服務和日期後，沿用現有 `search_slots` → `select_slot` → `confirm` 流程；最後建立預約時使用新選擇的 service/slot。

### Step snapshot 與去重

前端 task record 的每個 step snapshot 增加：

- 當時 response 的 `actions` labels/kinds；
- 使用者觸發該 step 的 selected action，只保存 action kind 和顯示 label，不保存 payload 內部 ID。

當 response 更新時，依 action kind 對應新出現的 step：`search_slots`、`select_slot`、`select_service` 對應同名流程 step，`confirm` 對應最後的 `create_appointment` 或 `get_task_status` step。既有 snapshot 不被新 response 覆蓋，確保 retry 前後的歷史仍可回看。

render 規則：

- terminal task 的最後 step 和 recovery task 的目前 step 顯示 snapshot 內容；已完成 task 最後的 `get_task_status` step 預設展開。
- 若最新 step snapshot 已有相同的摘要、錯誤或 recovery，task card 主內容不再重複渲染。
- 當助手訊息與 recovery explanation 完全相同時，只保留一份文字；`下一步怎樣做` 區塊保留 action context，但不重複 explanation。
- 歷史 step detail 顯示當時的「可用選項」和「你選擇了」紀錄；選項以文字／唯讀樣式呈現，不會再次送出 action。
- 非 terminal、非 recovery 的服務選擇和時段選擇流程仍由 task card 主內容展示目前可操作資料，避免隱藏尚未完成的選擇。

## 錯誤處理與相容性

- `select_service` 是 middleware allowlist 內的新 action；未知 action 仍被拒絕。
- 重新載入服務失敗時沿用既有 tool failure/recovery 流程，不清除 task card，也不暴露 backend 原始錯誤。
- 若 response 缺少 `actions`、`steps` 或 snapshot 資料，前端以空集合處理並保留現有主內容 fallback。
- 歷史 action 只顯示安全 label/kind，不顯示 slot ID、service ID、request ID 或 raw payload。
- 既有 `search_slots`、`select_slot`、`confirm`、`cancel` 和 `human_help` payload contract 保持不變。
- 不新增 browser storage；頁面重新載入後仍沿用目前的 session 行為。

## 驗證

新增或調整以下測試：

- recovery policy：`DUPLICATE_BOOKING` 只產生通用 `select_service`，不產生帶固定 service ID 的 `search_slots`。
- controller：`select_service` 重新查詢服務、清除舊選擇、返回動態服務清單和取消 action。
- controller：重新選擇服務後的日期／時段仍會傳入新的 service ID。
- frontend static contract：確認 snapshot 保存 actions/selected action、去重分支、完成步驟預設展開、selecting service 的取消 action 和安全顯示文字存在。
- `node --check frontend/app.js frontend/interaction-view.js frontend/mcp-client.js frontend/speech.js`。
- `python -m unittest discover -s tests -v`、`python -m unittest discover -s MCP/tests -v`、`python -m unittest discover -s middleware/tests -v`。
- `python -m compileall -q MCP middleware mock_backends frontend scripts tests`。

## 非目標

- 不改變 mock backend 的服務目錄或預約衝突判定。
- 不新增永久 task history API 或跨頁保存。
- 不重寫整個 task workspace，不改動與醫療預約無關的 domain flow。
- 不以 CSS 隱藏重複內容取代資料來源去重。

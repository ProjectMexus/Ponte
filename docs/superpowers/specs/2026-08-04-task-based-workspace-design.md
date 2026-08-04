# 任務式服務工作區設計

## 目標

將 Ponte 目前只有一個共享 `task-content` 的服務工作區，改成以「獨立任務」為單位的可收放任務列表。使用者可以在同一個 session 中完成多項查詢或辦事，而每項任務都會保留自己的進度、結果摘要及操作紀錄。

本次同時修正醫療查詢的資料生命週期：新的高階需求開始時，middleware 不再沿用上一個預約流程的暫存欄位，避免查詢結果被舊的 `selected_slot`、`slots` 或服務選擇資料遮蔽。

## 核准方案

採用前端任務工作區加 middleware 暫存資料清理的混合方案：

- 前端保存 session 內的任務卡片歷史，負責展開、收合及結果投影。
- middleware 保持既有 HTTP、action 和 speech contract，在新的高階需求開始時重設目前 workflow 的暫存 state。
- 不把工具名稱、request ID、FHIR resource type、內部 ID 或原始 JSON 暴露給一般使用者。
- 目前仍由新的文字／語音需求建立任務；UI action 更新目前任務。
- 任務識別與輸入通道保持可擴展，未來 LLM 的文字／語音確認可以繼續同一任務，而不必另建卡片。

## 非目標

- 本次不建立完整的 durable task history API。
- 本次不改變醫療 mock backend 的預約、task 或 receipt 資料格式。
- 本次不把 LLM 直接接入 workflow，也不允許 LLM 跳過既有確認節點。
- 本次不將任務歷史持久化到 browser storage；頁面重新載入後沿用現有 session 重建行為。
- 本次不重做左側對話紀錄、語音控制或既有 action payload。

## 架構與責任邊界

```text
使用者文字／語音／UI action
          │
          ▼
   TaskInput（目前由 app.js 組裝）
          │
          ▼
Interaction Controller / Workflow
          │
          ▼
   Middleware Task Manager
          │ 既有 InteractionResponse，加可選 task_id
          ▼
   TaskResponse 投影
          │
          ▼
前端 Task Workspace（任務歷史、收放、摘要）
```

Frontend 負責：

- 建立本地任務卡片並保存目前頁面 session 的任務歷史。
- 將每次 response 更新到正確的任務，而不是清空整個工作區。
- 根據 `task_state`、`steps`、`data` 和 `actions` 渲染用戶版 UI。
- 只讓目前等待輸入的任務顯示可操作控制；已結束任務只保留可查看內容。

Middleware 負責：

- 根據既有 intent 和 workflow 執行工具及確認流程。
- 在新的高階 message task 開始時清除上一個 workflow 的 transient data、steps、tool events、retry call 和 confirmation record。
- 對 action response 保持目前 task state，不在每次 action 時重設。
- 未來可在 response 加入 `task_id`，讓 frontend 使用 backend／LLM task identity 取代 local fallback。

LLM 或 intent recognizer 負責理解輸入和產生結構化意圖，但不直接改寫工作區，也不直接呼叫 mock backend。

### Middleware Task Manager

`middleware/task_manager/` 是 middleware 內管理目前 task lifecycle 的邊界，負責接收 `SessionState`、`ToolExecutionResult` 和 workflow recovery policy，並將合法狀態轉移投影為 `TaskResponse`。package 分為：

- `contracts.py`：task state、transition、recovery plan 和對外 response 欄位；
- `manager.py`：新 task、action chain、step/tool result、resume、cancel、complete 和 fail；
- `recovery.py`：backend error 或空結果到 `RecoveryPlan` 的 deterministic mapping；
- `transitions.py`：可允許狀態轉移與 terminal state 規則。

`InteractionController` 保留 intent 辨識和 workflow 順序，不再直接散落修改 task lifecycle。`SessionState` 仍是 in-memory session 容器；Task Manager 是它與 execution pipeline 之間的 task adapter。LLM 未來只能讀取白名單化的 `RecoveryPlan` 和 workflow context，再透過既有 action 或 `continueTask()` contract 繼續任務。

## 任務模型與擴展接口

目前前端任務記錄使用 local ID；後端 task ID 為可選的外部識別：

```js
{
  localId: "UI-TASK-1",
  backendTaskId: null,
  title: "查詢醫療預約",
  channel: "text", // text | voice | ui
  status: "running", // running | completed | cancelled | failed | human_handoff
  taskState: "querying", // querying | awaiting_user_input | ...
  currentStep: "load_appointments",
  response: {
    steps: [],
    data: {},
    actions: [],
    recovery: null
  },
  expanded: true
}
```

UI view layer 暴露以下責任清晰的操作：

```js
startTask({ channel, value, taskId })
updateTask(taskId, response)
continueTask(taskId, { channel, value })
toggleTask(taskId)
```

目前流程會由 `sendMessage()` 呼叫 `startTask()`，由 `handleAction()` 更新目前 task。`continueTask()` 先保留清晰的接口，不在本次強行實作 LLM confirmation router。未來 response 若帶有 `task_id`，任務路由優先使用 backend ID；沒有時使用 local ID。

任務是否建立或繼續，應由 task transition policy 決定，而不是由「是否點擊 button」決定。現在的 policy 是「新文字／語音需求建立；UI action 更新」；未來可以加入「目前任務等待確認時，文字／語音輸入繼續目前任務」。

## 任務生命週期與 UI 規則

```text
新需求
  ↓
建立並展開目前任務
  ↓
更新 steps／資料／actions
  ├─ completed       → 保留並收合
  ├─ cancelled       → 保留並收合
  ├─ awaiting_user_input → 保留原因並展開，等待補充／選擇
  ├─ failed          → 保留錯誤並收合
  └─ human_handoff   → 保留狀態並收合
```

每張任務卡由以下部分組成：

1. 標題／狀態列：顯示辦事項名稱和「進行中」「已完成」「已取消」或「需要再試一次」等用戶語言。
2. 任務內容：顯示流程 steps、目前資料及結果摘要。
3. 操作區：只在目前任務仍需要使用者輸入時顯示。

已完成任務自動收合，但標題列可以用鍵盤或滑鼠重新展開。最新執行中的任務自動展開；建立新任務時前一個任務收合但不刪除。

## Response 到資料摘要的映射

前端 renderer 必須按業務意圖選擇資料來源，而不是按物件鍵名的偶然順序選擇：

```text
data.intent === "medical_query"
  → appointments

醫療預約流程
  → selected_slot（確認／提交／完成）
  → slots（選擇時段）
  → services（選擇服務）

其他服務
  → 既有友善欄位白名單
```

醫療查詢每筆預約至少顯示：

- 服務名稱；
- 日期；
- 時間範圍；
- 服務地點；
- 狀態。

空資料顯示「目前沒有已預約的醫療服務。」。服務和時段維持現有日期、時間、地點及分鐘數的本地化格式。未知地點只顯示「服務地點」，不可顯示 `LOC-*` 原值。

每個任務的 steps 只顯示映射後的中文文案，例如「確認現有預約」「查找可預約時段」「確認預約」；不得將 `tool_name`、`step_id`、request ID 或 raw status 作為使用者可見文字。

## Middleware state reset

在 `InteractionController.handle_message()` 的新高階需求路徑開始前，保留 `session_id`，重設：

- `data` 中上一個 workflow 的業務暫存欄位；
- `steps`；
- `tool_events`；
- `last_tool_call`；
- `confirmation_record`；
- `last_error`。

新的 intent 和新的工具結果再寫入同一個 `SessionState`。`handle_action()` 不執行這個 reset，確保選擇服務、選擇時段和確認預約仍屬於同一 workflow。

這種 reset 只影響 middleware 的目前 task state；已建立的 mock appointment、medical task 和 receipt 不會被刪除。

## 錯誤與相容性

- middleware response error：由 Task Manager 的 recovery policy 分類。缺少資料、沒有名額和暫時性 backend error 標記為 `awaiting_user_input`，保留目前 task 並回傳 `recovery` 和可執行 actions；權限、未知 tool 或 response schema 錯誤才標記為 `failed`。
- 醫療預約搜尋返回空時段也視為 `NO_AVAILABLE_SLOTS`，前端顯示額滿／無時段原因及替代方案，而不是當作普通成功。
- `error` 保留 machine-readable code；`recovery.explanation`、`required_fields` 和 action label 使用 user-facing 白名單，不顯示 request ID、tool name、FHIR resource type、內部 ID 或 raw backend JSON。
- HTTP 或 middleware unavailable：前端保留已建立任務，允許重新輸入；不清空左側對話或歷史任務。
- retry、cancel、confirm、human help 的既有 action payload 不變。
- speech input 仍先填回文字框，再由送出流程建立或繼續任務。
- 大字、高對比、focus-visible、ARIA、手機版單欄佈局都必須保留。

## 文件同步

本功能需要同步更新：

- `docs/PonteArch.md`：新增 Task Workspace、TaskInput／TaskResponse 和前端任務歷史的架構說明。
- `README.md`：將一般使用者驗收描述改為任務卡和服務摘要，移除「看到 tool event」的產品表述。
- `frontend/README.md`：說明任務卡收放、查詢結果摘要和未來可延伸的輸入方式。
- 本設計文件及後續 implementation plan：保持接口名稱、狀態命名和資料優先級一致。

## 驗證與完成條件

1. 前端靜態 contract 測試驗證 task list、start／update／continue 接口、收放語意和資料優先級。
2. middleware unit test 驗證新的高階 message 清理 stale workflow data，action chain 不被清理。
3. Task Manager unit test 驗證合法／非法 transition、recovery policy、可恢復錯誤和 hard failure。
4. integration test 驗證同一 session 先完成預約、再進行查詢時，response 只使用新的查詢 data；可恢復錯誤後 action 仍可繼續同一 workflow。
5. frontend static contract 驗證 `awaiting_user_input` 卡片保持展開、recovery options 使用同一 task ID，且不暴露內部識別值。
6. 所有 frontend JavaScript 通過 `node --check`。
7. 所有既有 Python tests 通過。
8. 本地 smoke check 驗證：查詢卡片顯示預約結果；預約流程的進行中卡片顯示 steps；錯誤時卡片保留原因和下一步；恢復後沿用同一張卡；完成後卡片收合；舊卡片可重新展開；手機寬度仍可操作。

完成條件是：使用者可以在工作區分辨多個獨立辦事項，看到目前任務的每個步驟，並在任務結束後回看收合的結果；未來 LLM 的對話式確認不需要重寫任務卡片模型。

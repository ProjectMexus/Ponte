# 可恢復任務錯誤與 Task Manager 設計

## 目標

當 workflow 中的 backend 或工具呼叫失敗時，middleware 不應只把目前 task 標成終止錯誤。對於可以透過補充資料、改選方案或重試而繼續的失敗，middleware 要產生結構化的恢復方案，讓前端向使用者說明原因並提供下一步；未來 LLM 可以讀取同一份方案來理解使用者的補充內容，但不能直接繞過既有 workflow 或確認節點。

本設計把 task lifecycle、狀態轉移、工具結果接入和 recovery policy 收斂到 `middleware/task_manager/`，讓 `InteractionController` 專注於 intent 與 workflow 編排。Intent LLM 與 Task Recovery LLM 是兩個不同的能力邊界：前者理解使用者輸入，後者理解 backend/tool 結果並產生下一步說明，不能共用同一個 prompt、context 或執行入口。

## 範圍

- 新增 `awaiting_user_input` 作為非終止 task state。
- 新增 `Task Manager` package，集中管理目前 session task 的 transition、tool result 接入和 response projection。
- 將 Intent LLM 與 Task Recovery LLM 分開管理；前者只產生 intent，後者只產生結構化恢復方案。
- 將 backend error 與空的可用時段結果轉換為 `RecoveryPlan`。
- 支援缺少資料、沒有名額、暫時性 backend error 和不可安全恢復錯誤四種 policy 分類。
- 前端 task card 顯示 recovery 說明和既有 action options，恢復 action 更新同一張卡片。
- 更新架構文件、task workspace spec 及測試 contract。

## 非目標

- 本次不接入新的實際 LLM provider，也不把原始 error、request ID、tool name 或 backend JSON 傳給使用者。
- 本次不新增 durable task history API、browser storage 或 backend task schema。
- 本次不讓 LLM 直接呼叫 tool、決定 URL／HTTP method，或跳過服務／時段／確認流程。
- 本次不把自然語言補充輸入自動路由回同一 task；保留既有 `continueTask(taskId, input)` contract，供後續 LLM confirmation router 使用。

## 架構

```text
使用者文字／語音
          │
          ▼
   Intent LLM / IntentRecognizer
   user input → IntentDecision
          │
          ▼
   InteractionController
   workflow order
          │
          ▼
   ExecutionPipeline / backend result
          │ sanitised result
          ▼
   Task Recovery LLM / deterministic fallback
   backend result → RecoveryPlan
          │
          ▼
   middleware/task_manager
   ├─ contracts      public task/recovery values
   ├─ manager        lifecycle and tool-result integration
   ├─ recovery       deterministic policy and sanitisation
   ├─ interpreter    Task Recovery LLM interface
   └─ transitions    allowed state transitions
          │
          ├───────────────┐
          ▼               ▼
   SessionState      ExecutionPipeline
   current task      ToolExecutionResult
          │               │
          └───────┬───────┘
                  ▼
             TaskResponse
                  │
                  ▼
        Frontend Task Workspace
```

### 模組責任

`middleware/task_manager/contracts.py` 定義 task 狀態、transition、recovery plan 和對外 response 使用的結構化欄位。它不依賴 HTTP server 或特定 backend。

`middleware/task_manager/manager.py` 是 task lifecycle 的唯一入口。它接收既有 `SessionState` 和 `ToolExecutionResult`，提供下列操作：

```python
start_new_task(state)
start_action(state)
record_tool_result(state, result, step_id, input_data)
request_user_input(state, recovery_plan)
complete(state, message)
cancel(state, message)
fail(state, message)
```

`middleware/task_manager/recovery.py` 是 deterministic policy。它只使用白名單化的 error code、workflow step、目前 task data 及 backend 回傳的候選資料產生 `RecoveryPlan`；不執行 action。

`middleware/task_manager/interpreter.py` 定義 Task Recovery LLM 的獨立介面。它接收已 sanitise 的 `ToolExecutionResult`、workflow step 和 `RecoveryPlan` context，輸出符合 `RecoveryPlan` 的 user-facing explanation、required fields 和 options；不接收原始 intent prompt，不負責 intent recognition，也不直接呼叫 tool。第一版由 deterministic recovery policy 實作 fallback，未來可注入獨立的 recovery LLM client。

`middleware/task_manager/transitions.py` 定義狀態轉移規則。`awaiting_user_input` 可以回到 `querying`、`selecting_service`、`selecting_slot` 或 `awaiting_confirmation`，也可以轉為 `cancelled` 或 `human_handoff`；`completed`、`cancelled`、`failed` 和 `human_handoff` 是 terminal state。

`middleware/session.py` 仍保留 `SessionState` 和 `SessionStore` 作為 in-memory session 容器。Task Manager 透過它保存目前 workflow 的資料，避免重做 session persistence contract；controller 不再直接散落地修改 lifecycle 欄位。

## TaskResponse contract

可恢復錯誤的 response 仍沿用既有 `assistant_message`、`steps`、`data` 和 `actions` 欄位，增加可選的 `recovery`：

```json
{
  "task_state": "awaiting_user_input",
  "current_step": "search_slots",
  "assistant_message": "目前選擇的服務在這段期間沒有可預約時段。你可以換日期再搜尋，或取消這次預約。",
  "error": {
    "code": "NO_AVAILABLE_SLOTS",
    "message": "目前沒有可用時段",
    "retryable": false
  },
  "recovery": {
    "category": "availability",
    "reason_code": "NO_AVAILABLE_SLOTS",
    "explanation": "目前的服務和日期範圍沒有可預約名額。",
    "required_fields": [],
    "options": [
      {
        "action": "search_slots",
        "label": "換日期再搜尋",
        "payload": {}
      },
      {
        "action": "cancel",
        "label": "取消這次預約"
      }
    ]
  },
  "actions": [
    {"kind": "search_slots", "label": "換日期再搜尋", "payload": {}},
    {"kind": "cancel", "label": "取消這次預約"}
  ]
}
```

`recovery.options` 是供 LLM 和其他 task adapter 理解的語義資料；`actions` 是前端唯一可以執行的 action 白名單。action payload 可攜帶 workflow 所需的內部值，但 label、explanation 和其他 user-facing text 不得包含 request ID、tool name、FHIR type 或 raw backend message。

Task Manager 的 response serializer 會把每個 `RecoveryOption` 投影為既有 action 形狀：`action` 轉成 `kind`，保留白名單化的 `label` 和受控 `payload`。因此 frontend 不需要理解 `RecoveryPlan` 的內部語義，也不會直接從 recovery object 執行未知 action。

`required_fields` 使用以下形狀描述需要使用者補充的資料：

```json
{
  "name": "contact_phone",
  "label": "聯絡電話",
  "input_type": "text",
  "reason": "服務中心需要聯絡方式才能繼續。"
}
```

本版只負責顯示 `required_fields` 並保留 task；後續 LLM/router 可以把文字／語音補充轉為同一 task 的 `continueTask` 或受控 action。

## Recovery policy

| 類型 | canonical reason code | task state | 方案 |
| --- | --- | --- | --- |
| 缺少資料 | `MISSING_REQUIRED_FIELD` | `awaiting_user_input` | 顯示 required fields 和補充原因 |
| 沒有名額 | `SCHEDULE_FULL`、`NO_AVAILABLE_SLOTS` | `awaiting_user_input` | 顯示額滿原因，提供候選日期／時段或重新搜尋 |
| 暫時性故障 | `BACKEND_UNAVAILABLE`、`BACKEND_TIMEOUT` | `awaiting_user_input` | 提供既有 `retry`、`cancel`、`human_help` actions |
| 不可安全恢復 | 權限錯誤、未知 tool、response schema 錯誤 | `failed` | 保留錯誤摘要，提供人工協助；不重試可能造成副作用的 action |

醫療預約搜尋即使 backend 成功但返回空 list，也要由 medical recovery policy 轉成 `NO_AVAILABLE_SLOTS`。若 backend error details 提供候選資料，policy 只抽取日期、時間、服務名稱和可供 action 使用的受控 payload；沒有候選資料時只提供重新搜尋或取消。

每個 action 開始時 Task Manager 清除目前 recovery；action 成功後回到 workflow 的下一個 state，action 失敗後以新的 error 和 recovery 覆蓋目前 recovery。新的高階 message 仍由 `reset_for_new_task()` 清理整個 transient workflow；action chain 不執行 reset。

## 前端行為

- `awaiting_user_input` 不列入 `TERMINAL_TASK_STATES`，task card 保持展開。
- task body 顯示 recovery explanation、required fields 和 options；options 送到既有 `handleAction(action, taskId)`。
- 替代時段仍使用 `search_slots`，不新增繞過 confirmation 的 endpoint。
- `failed`／`error`、`completed`、`cancelled` 和 `human_handoff` 維持收合規則。
- frontend 不渲染 recovery 的 raw details；未知欄位不進入 generic data allowlist。
- transport-level middleware unavailable 仍沿用現有 global error 和 task preservation 行為；能收到 middleware response 的 backend error 則優先使用 recovery contract。

## 驗證

1. Task Manager unit tests 驗證合法／非法 transition、terminal state、reset 和 response serialization。
2. Recovery policy tests 驗證 missing field、full schedule、empty slots、retryable backend error 和 hard failure。
3. Controller tests 驗證 tool failure 後 task 仍可透過 action 繼續，且同一 session 的 services／date range 不被 reset。
4. Integration test 驗證一次 workflow 在可恢復錯誤後重新搜尋，最後仍能走到 confirmation；新的高階 message 才會清除舊 workflow。
5. Frontend static tests 驗證 `awaiting_user_input` 卡片保持展開、recovery options 使用同一 task ID 且不暴露內部識別值。
6. 執行所有 frontend `node --check`、Python unittest、compile check、`git diff --check` 和本地 smoke check。

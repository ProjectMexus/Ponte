# Ponte Demo 系統框架文檔

## 1. 文檔目的

本文定義 Ponte 比賽 Demo 的系統邊界、核心架構、模組責任、任務流程及實作優先級。

本 Demo 的目標不是完整接入澳門政府、醫療及社福生產系統，而是透過 Mock API、模擬 RPA 及簡化 FHIR 資源，展示以下技術與產品命題：

1. 長者可以使用自然粵語表達公共服務需求。
2. Ponte 能將模糊需求轉換為結構化任務。
3. 任務按照受控 Workflow 執行，而不是由 LLM 任意操作。
4. Ponte 能協調一戶通、醫療及社會福利等不同服務。
5. 高風險操作必須經過身份驗證和使用者確認。
6. 任務提交後仍會持續追蹤，直至完成、失敗或轉交人工。
7. 每個重要操作都有畫面、回執及完整 Action Receipt。

Ponte 的核心不是語音問答，而是將長者需求轉化為可執行、可追蹤及可交接的公共服務任務。

------

# 2. Demo 約束

## 2.1 時間約束

開發時間少於 10 天，因此本 Demo 採用以下原則：

- 所有政府、醫療及社福系統均由 Ponte Backend 模擬；
- 不接入真實身份資料或醫療資料；
- 不實作完整 OAuth、FHIR Server 或政府級 IAM；
- 不追求通用 Agent；
- 不建立完整 BPMN 管理平台；
- 只實作一條主要端到端流程；
- 其他服務以較短支線展示架構擴展能力。

## 2.2 設計原則

### Workflow-first

LLM 負責理解需求、抽取資料和解釋流程，但不能自行決定跳過流程節點。

正式執行路徑由 Workflow 定義。

### Durable Task

每個任務都保存持久狀態。即使對話結束、服務重啟或需要等待外部回覆，任務仍可以繼續執行。

### Human-in-the-loop

身份驗證、敏感資料存取、正式提交及高影響操作必須設置確認節點。

### Visible Execution

Ponte 必須同步展示：

- 正在使用的服務；
- 正在填寫的資料；
- 當前流程步驟；
- 下一步操作；
- 等待確認的內容；
- 提交結果及官方回執。

這對應「AI 負責操作，長者看得見、聽得懂，並保留確認、修正和停止控制權」的產品要求。

### Evidence-first

每個重要步驟必須產生可核實的事件紀錄，而不是只保存最終聊天內容。

------

# 3. 整體架構

```text
┌─────────────────────────────────────────────┐
│              User Interface                 │
│                                             │
│  Voice Input  Conversation  Visual Sandbox  │
└──────────────────────┬──────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────┐
│           Interaction Controller            │
│                                             │
│  ASR / Speech Model                         │
│  Intent Recognition                         │
│  Entity Extraction                          │
│  Response Generation                        │
└──────────────────────┬──────────────────────┘
                       │ Structured Task Request
                       ▼
┌─────────────────────────────────────────────┐
│            Workflow Orchestrator            │
│                                             │
│  Workflow Definition                        │
│  Step Execution                             │
│  Confirmation Gates                         │
│  Branching and Error Handling               │
└───────────────┬─────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────┐
│          Durable Task Runtime               │
│                                             │
│  Persistent State                           │
│  Timer / Scheduled Check                    │
│  Retry / Timeout                            │
│  External Event Handling                    │
│  Human Takeover                             │
└───────────────┬─────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────┐
│          Policy and Guardrail Layer         │
│                                             │
│  Identity Context                           │
│  Delegation and Consent                     │
│  Risk Classification                        │
│  Tool Permission                            │
│  Submission Confirmation                    │
└───────────────┬─────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────┐
│          MCP / Tool Adapter Layer           │
│                                             │
│  One Account MCP Server                     │
│  Medical MCP Server                         │
│  Social Welfare MCP Server                  │
│  Notification MCP Server                    │
└───────┬────────────┬────────────┬───────────┘
        │            │            │
        ▼            ▼            ▼
┌────────────┐ ┌────────────┐ ┌──────────────┐
│ Mock       │ │ Mock       │ │ Mock Social  │
│ One Account│ │ Medical    │ │ Welfare      │
│ API / RPA  │ │ API / FHIR │ │ API          │
└────────────┘ └────────────┘ └──────────────┘

                ┌─────────────────────────────┐
                │ Evidence and Receipt Store  │
                │                             │
                │ Events / Screenshots        │
                │ Confirmations / Receipts    │
                │ Final Action Receipt        │
                └─────────────────────────────┘
```

## 3.1 Task Workspace 與對話輸入

Frontend 的服務工作區以獨立任務卡片呈現，而不是用一個共享區域覆蓋上一個 response。每次新的高階需求會建立一個 UI task；後續選擇服務、選擇時段、確認或其他輸入會更新同一個 task。任務完成、取消、失敗或轉交人工後保留在工作區並自動收合，最新執行中的 task 則展開顯示 steps、摘要資料及下一步操作。

```text
文字／語音／UI action
          │
          ▼
       TaskInput
          │
          ▼
Interaction Controller / Workflow
          │
          ▼
       TaskResponse
          │
          ▼
Frontend Task Workspace
  ├─ task history
  ├─ visible steps
  ├─ friendly data summaries
  └─ next actions
```

`TaskInput` 的輸入通道可以是 `text`、`voice` 或 `ui`，並可帶有可選 `task_id`。目前 frontend 使用 local task ID，middleware response 未來可以提供 backend／LLM task ID；任務路由接口因此不把「繼續任務」綁定在 button click 上。這讓未來的 LLM 對話可以在使用者說出「確認」「改下午」或補充資料時，繼續目前等待中的 task。

Frontend 只負責任務歷史和用戶版投影；Workflow Orchestrator 仍負責流程順序、確認節點、工具權限和實際執行。新的高階需求開始時，middleware 會清理上一個 `SessionState` workflow 的 transient data、steps、tool events、retry call 和 confirmation record，但不會刪除已建立的 mock appointment、durable task 或 receipt。UI task history 與 durable backend task 是兩個互補層次：前者服務於本次對話的可理解工作區，後者負責業務狀態和長時間追蹤。

## 3.2 Middleware Task Manager 與可恢復錯誤

Frontend Task Workspace 只負責 task history 和用戶版投影；middleware 的 `Task Manager` 負責目前 session task 的狀態、工具結果接入、合法轉移及恢復方案。這個邊界避免 `InteractionController`、LLM adapter 或前端各自維護一套 task lifecycle。

```text
InteractionController
  ├─ intent recognition
  └─ workflow order
          │
          ▼
middleware/task_manager/
  ├─ contracts.py      Task state / RecoveryPlan contract
  ├─ manager.py        lifecycle and tool-result integration
  ├─ recovery.py       backend result → recovery policy
  └─ transitions.py    allowed transitions / terminal states
          │
          ├──────────────► SessionState / SessionStore
          └──────────────► ExecutionPipeline / ToolExecutionResult
                              │
                              ▼
                         TaskResponse
```

Task Manager 保留 `SessionState` 作為目前 workflow 的 in-memory 容器，但成為修改 task lifecycle 的唯一入口。正常 workflow 由 `querying`、`selecting_service`、`selecting_slot` 和 `awaiting_confirmation` 轉移；工具或 backend 返回可處理的錯誤時，轉移到非終止的 `awaiting_user_input`。此狀態會保留原 task、steps 和已知資料，並附上 `RecoveryPlan`，讓前端說明缺少的資料、額滿原因、候選方案或重試方式。

可恢復錯誤的 response 使用既有 `TaskResponse` 欄位，加上：

```json
{
  "task_state": "awaiting_user_input",
  "error": {"code": "NO_AVAILABLE_SLOTS", "retryable": false},
  "recovery": {
    "category": "availability",
    "reason_code": "NO_AVAILABLE_SLOTS",
    "explanation": "目前的服務和日期範圍沒有可預約名額。",
    "required_fields": [],
    "options": [{"action": "search_slots", "label": "換日期再搜尋", "payload": {}}]
  }
}
```

`recovery` 是 LLM-ready 的語義資料，但 LLM 不直接執行 tool。前端只把白名單化的 `options` 轉為既有 actions；例如替代時段仍回到 `search_slots`，預約提交仍必須經過原本的 `confirm`。只有 `completed`、`cancelled`、`failed` 和 `human_handoff` 會自動收合；`awaiting_user_input` 保持展開，直到使用者補充資料、選擇方案、取消或轉交人工。

## 3.3 Intent LLM 與 Task Recovery LLM 分離

Ponte 有兩個不同目的的 LLM 邊界，必須分開管理：

```text
使用者文字／語音
        │
        ▼
Intent LLM / IntentRecognizer
        │ 只產生 IntentDecision
        ▼
InteractionController / Workflow
        │ 呼叫受控 tool
        ▼
ToolExecutionResult / backend response
        │ sanitise 後
        ▼
Task Recovery LLM
        │ 只產生 RecoveryPlan
        ▼
Task Manager → TaskResponse → Frontend Task Workspace
```

Intent LLM 只理解使用者想做什麼，例如查詢預約或開始預約；它不解讀 backend failure，也不決定 recovery message。Task Recovery LLM 只理解工具／backend 返回的成功、失敗、缺少欄位、額滿或候選資料，向使用者說明原因並提出下一步可能方案；它不辨識 intent、不改寫 workflow state、不直接呼叫 tool。

兩者必須使用不同的 interface、system prompt、context allowlist、設定和測試 double。`middleware/intent.py` 管理 `IntentRecognizer`；`middleware/task_manager/interpreter.py` 管理 `TaskRecoveryInterpreter` 及獨立的 OpenAI-compatible client。Task Recovery LLM 由 `PONTE_TASK_RECOVERY_LLM_API_URL`、`PONTE_TASK_RECOVERY_LLM_API_KEY` 和 `PONTE_TASK_RECOVERY_LLM_MODEL` 管理；設定 endpoint 後，failure 會記錄 `operation=task_recovery` 的 send/receive/error 事件。未設定或 provider 失敗時才使用 deterministic recovery policy 作為 fallback。所有模型輸出都必須先驗證成 `RecoveryPlan`，再由 Task Manager 轉成既有 action；LLM 不可跳過確認節點。

Intent LLM 的 `PONTE_LLM_*` 設定不可作為 recovery client 的隱式 fallback；兩者即使使用同一個 provider，也必須透過兩組設定、兩個 prompt 和兩個 interface 管理。這樣可以從 log 清楚分辨「理解使用者意圖」與「理解 backend failure」兩個步驟。

Task Manager 的 response serializer 會將 `RecoveryPlan.options` 映射為既有 `actions[{kind, label, payload}]`，Frontend 只消費 actions，不直接執行 LLM 輸出或 recovery object 中的未知欄位。

------

# 4. 核心架構決策

## 4.1 LLM 不直接控制業務流程

LLM 的輸出必須先轉換成結構化任務：

```json
{
  "intent": "reschedule_medical_appointment",
  "subject": "self",
  "parameters": {
    "appointment_id": "APT-10021",
    "preferred_date_range": {
      "from": "2026-08-10",
      "to": "2026-08-14"
    }
  },
  "required_services": [
    "medical"
  ],
  "risk_level": "medium",
  "workflow_type": "medical_reschedule_v1"
}
```

Workflow Orchestrator 根據 `workflow_type` 啟動預先定義的流程。

LLM 可以：

- 判斷意圖；
- 抽取日期、服務及人物關係；
- 向長者補問缺少資料；
- 將流程狀態解釋成自然語言；
- 對錯誤訊息進行易懂解釋。

LLM 不可以：

- 自行跳過身份驗證；
- 自行提交高風險操作；
- 任意修改 Workflow 狀態；
- 直接寫入外部 Mock 系統資料庫；
- 宣稱任務完成而未收到工具結果。

## 4.2 MCP 是工具接入層

MCP 用於將不同領域能力暴露為標準化工具。

示例：

```text
one_account.search_service
one_account.get_application_requirements
one_account.submit_application
one_account.get_application_status

medical.get_appointments
medical.search_available_slots
medical.reschedule_appointment
medical.get_appointment_status

social_welfare.search_services
social_welfare.create_referral
social_welfare.get_referral_status

notification.notify_family_member
notification.send_reminder
```

MCP 不負責：

- 長期任務狀態；
- 風險判斷；
- 身份及家庭授權；
- 跨工具流程順序；
- 人工接管；
- Action Receipt。

------

# 5. Workflow Orchestrator

## 5.1 職責

Workflow Orchestrator 是 Ponte 的核心控制元件，負責：

1. 根據結構化意圖選擇 Workflow。
2. 執行預定義步驟。
3. 判斷當前步驟是否需要使用者確認。
4. 調用 MCP 工具。
5. 驗證工具回傳結果。
6. 更新 Durable Task 狀態。
7. 處理錯誤、重試及人工接管。
8. 產生每個步驟的證據事件。

## 5.2 Workflow 定義方式

由於 Demo 時間有限，不建議部署完整 BPMN 平台。

可以使用程式碼或 JSON 定義簡化 Workflow：

```json
{
  "workflow_id": "medical_reschedule_v1",
  "steps": [
    {
      "id": "load_appointment",
      "type": "tool",
      "tool": "medical.get_appointments"
    },
    {
      "id": "select_appointment",
      "type": "user_selection"
    },
    {
      "id": "search_slots",
      "type": "tool",
      "tool": "medical.search_available_slots"
    },
    {
      "id": "select_slot",
      "type": "user_selection"
    },
    {
      "id": "confirm_submission",
      "type": "confirmation",
      "risk": "medium"
    },
    {
      "id": "submit",
      "type": "tool",
      "tool": "medical.reschedule_appointment"
    },
    {
      "id": "wait_for_confirmation",
      "type": "durable_wait"
    },
    {
      "id": "notify_user",
      "type": "notification"
    }
  ]
}
```

## 5.3 支援的步驟類型

Demo 最少支援：

- `tool`
- `user_input`
- `user_selection`
- `confirmation`
- `condition`
- `durable_wait`
- `notification`
- `human_handoff`
- `complete`
- `failed`

------

# 6. Durable Agent Workflow

## 6.1 定位

Durable Workflow 不負責理解自然語言，而是確保任務在長時間執行過程中不會丟失狀態。

文件要求 Ponte 在提交後持續檢查官方狀態、補件通知、人工接手及長者下一步，而不是停留在「已替你填好」。

## 6.2 任務狀態

```text
CREATED
  ↓
COLLECTING_INFORMATION
  ↓
WAITING_FOR_CONFIRMATION
  ↓
WAITING_FOR_AUTHENTICATION
  ↓
EXECUTING
  ↓
SUBMITTED
  ↓
WAITING_FOR_EXTERNAL_RESULT
  ├── NEEDS_ADDITIONAL_INFORMATION
  ├── HUMAN_HANDOFF
  ├── COMPLETED
  ├── FAILED
  └── CANCELLED
```

## 6.3 持續追蹤機制

Demo 不需要建立高頻分布式 heartbeat。

可以採用簡化方式：

1. Workflow 提交任務。
2. Backend 保存下一次檢查時間。
3. Background Scheduler 定期執行 status check。
4. Mock Service 在指定時間後改變狀態。
5. Scheduler 偵測狀態變化。
6. Durable Task 恢復執行。
7. Ponte 通知長者或要求下一步操作。

例如：

```text
14:00 提交覆診改期
14:00 任務狀態：WAITING_FOR_EXTERNAL_RESULT
14:01 Mock 醫療系統：PROCESSING
14:02 Mock 醫療系統：CONFIRMED
14:02 Ponte 恢復 Workflow
14:02 產生確認通知及 Action Receipt
```

## 6.4 必要機制

### Idempotency

每次正式提交必須包含 `idempotency_key`，避免重試時重複提交。

```json
{
  "idempotency_key": "task-3821-step-submit-1"
}
```

### Retry

只對暫時性錯誤自動重試，例如：

- 網絡錯誤；
- Mock Service 暫時不可用；
- HTTP 502；
- 查詢超時。

資料驗證失敗或權限不足不能自動重試。

### Timeout

每個等待狀態設置最大等待時間。超時後：

- 通知長者；
- 將任務標記為異常；
- 或轉交人工。

### Event Resume

Workflow 可以因以下事件恢復：

- 使用者確認；
- 使用者補交資料；
- Mock 系統狀態更新；
- 家屬回覆；
- 人工接管；
- Timer 到期。

------

# 7. Policy 與 Guardrail

Guardrail 的作用不是過濾對話內容，而是控制 AI 可以做甚麼、何時可以做，以及何時必須停止。

## 7.1 風險等級

| 等級 | 示例                             | 控制                   |
| ---- | -------------------------------- | ---------------------- |
| R0   | 查詢一般服務資訊                 | 不需身份驗證           |
| R1   | 填寫非敏感資料、搜尋預約         | 使用者口頭確認         |
| R2   | 改期、提交申請、建立轉介         | 明確確認及模擬身份驗證 |
| R3   | 存取醫療紀錄、代理他人、緊急共享 | 強制身份驗證或人工接管 |

## 7.2 確認節點

提交前，UI 必須顯示：

```text
你將把覆診日期由：

2026 年 8 月 12 日 10:30

更改為：

2026 年 8 月 14 日 15:00

地點：仁伯爵綜合醫院

確認提交？
```

確認記錄包括：

- 顯示內容；
- 使用者選擇；
- 確認時間；
- 任務 ID；
- Workflow Step ID。

## 7.3 權限限制

每個 Workflow 只可以使用預先允許的工具。

```json
{
  "workflow": "medical_reschedule_v1",
  "allowed_tools": [
    "medical.get_appointments",
    "medical.search_available_slots",
    "medical.reschedule_appointment",
    "medical.get_appointment_status",
    "notification.send_reminder"
  ]
}
```

即使 LLM 嘗試調用其他工具，Tool Router 亦必須拒絕。

------

# 8. Mock Service Layer

## 8.1 Mock 一戶通

主要實體：

```text
User
Service
Application
ApplicationStatus
DocumentRequirement
```

建議接口：

```http
GET  /mock/one-account/services
GET  /mock/one-account/services/{serviceId}
POST /mock/one-account/applications
GET  /mock/one-account/applications/{applicationId}
POST /mock/one-account/applications/{applicationId}/documents
```

可展示場景：

- 搜尋長者津貼服務；
- 顯示申請條件；
- 預填表格；
- 確認提交；
- 追蹤申請狀態；
- 模擬補件通知。

## 8.2 Mock 醫療系統

Demo 不需要實作完整 FHIR Server。

可以採用 FHIR-inspired JSON，模擬以下資源：

- `Patient`
- `Appointment`
- `Schedule`
- `Slot`
- `Task`

示例：

```json
{
  "resourceType": "Appointment",
  "id": "APT-10021",
  "status": "booked",
  "start": "2026-08-12T10:30:00+08:00",
  "serviceType": "Cardiology Follow-up",
  "location": "仁伯爵綜合醫院"
}
```

建議接口：

```http
GET  /mock/medical/patients/{patientId}/appointments
GET  /mock/medical/slots
POST /mock/medical/appointments/{appointmentId}/reschedule
GET  /mock/medical/tasks/{taskId}
```

可展示場景：

- 查詢覆診；
- 搜尋可選日期；
- 提交改期；
- 等待醫院確認；
- 取得新的覆診安排；
- 產生提醒。

## 8.3 Mock 社會福利系統

主要實體：

```text
WelfareService
Referral
Case
CaseWorker
ReferralStatus
```

建議接口：

```http
GET  /mock/social-welfare/services
POST /mock/social-welfare/referrals
GET  /mock/social-welfare/referrals/{referralId}
POST /mock/social-welfare/referrals/{referralId}/assign
```

可展示場景：

- 搜尋長者接送或陪診服務；
- 收集轉介資料；
- 取得長者資料共享同意；
- 建立轉介；
- 等待社工接手；
- 顯示負責人及聯絡時間。

## 8.4 Mock RPA

RPA 不需要真正控制完整瀏覽器。

可以將每個操作模擬成：

1. Backend 返回一個 RPA step event。
2. Frontend 顯示對應的模擬頁面。
3. 系統逐步高亮正在填寫的欄位。
4. 每個步驟保存 screenshot。
5. 最後生成模擬官方回執。

這樣可以展示「可視化受控執行」，而不需要處理真實網站登入、DOM 變動和反自動化限制。

------

# 9. Action Receipt

每個完成或失敗的任務產生一份 Action Receipt。

文件要求 Action Receipt 記錄使用的服務、填寫資料、身份授權、使用者確認、提交結果、官方回執、操作截圖及後續狀態。

## 9.1 建議資料結構

```json
{
  "receipt_id": "REC-20260803-001",
  "task_id": "TASK-3821",
  "user_request": "我想將下星期的覆診推遲。",
  "interpreted_intent": "reschedule_medical_appointment",
  "workflow": "medical_reschedule_v1",
  "services_used": [
    "mock-medical-system"
  ],
  "confirmations": [
    {
      "step": "confirm_submission",
      "confirmed_at": "2026-08-03T14:01:20+08:00"
    }
  ],
  "actions": [
    {
      "tool": "medical.reschedule_appointment",
      "status": "success",
      "timestamp": "2026-08-03T14:01:25+08:00"
    }
  ],
  "official_receipt": {
    "reference": "MED-RS-88219"
  },
  "screenshots": [
    "step-01-current-appointment.png",
    "step-02-selected-slot.png",
    "step-03-confirmation.png",
    "step-04-receipt.png"
  ],
  "final_status": "completed"
}
```

------

# 10. 主要 Demo 流程

## 10.1 建議主流程

主流程建議使用：

> 長者要求更改覆診時間，並在完成後通知家屬。

理由：

- 容易理解；
- 有清晰的原始狀態及目標狀態；
- 可以展示資料查詢；
- 可以展示使用者選擇；
- 可以展示正式提交確認；
- 可以展示 Durable Workflow；
- 可以展示家屬通知；
- 可以展示官方回執和 Action Receipt。

## 10.2 Demo 流程

```text
長者：
「我下星期三覆診，但我有事去唔到，
可唔可以幫我改到星期五？」

1. Speech / ASR 取得需求
2. LLM 抽取日期和改期意圖
3. 啟動 medical_reschedule_v1
4. 查詢現有預約
5. 在 Visual Sandbox 顯示預約
6. 查詢星期五可用時段
7. 長者選擇時段
8. 系統回讀日期、時間和地點
9. 長者明確確認
10. Mock 醫療系統接受提交
11. Workflow 進入 WAITING_FOR_EXTERNAL_RESULT
12. Background Scheduler 查詢狀態
13. Mock 醫療系統返回 CONFIRMED
14. Workflow 恢復
15. 通知長者及家屬
16. 產生 Action Receipt
```

## 10.3 次要展示流程

### 一戶通支線

```text
查詢長者津貼
→ 解釋資格
→ 預填資料
→ 使用者確認
→ 模擬提交
→ 等待補件
```

### 社福支線

```text
提出陪診需要
→ 搜尋服務
→ 取得資料共享同意
→ 建立轉介
→ 等待社工接手
```

支線不必做到與主流程相同的完整 UI，可透過較短操作展示 MCP adapter 和 Workflow 擴展能力。

------

# 11. 最小資料模型

## User

```text
id
name
preferred_language
mock_identity_level
```

## Delegation

```text
id
user_id
delegate_name
delegate_relationship
allowed_actions
status
```

## Task

```text
id
user_id
workflow_type
status
current_step
risk_level
created_at
updated_at
next_check_at
```

## TaskEvent

```text
id
task_id
step_id
event_type
input
output
timestamp
```

## Confirmation

```text
id
task_id
step_id
displayed_content
decision
confirmed_at
```

## ExternalOperation

```text
id
task_id
service
operation
idempotency_key
external_reference
status
```

## Evidence

```text
id
task_id
step_id
evidence_type
file_path
created_at
```

------

# 12. 建議技術邊界

## 必須實作

- 語音或文字輸入；
- LLM 意圖識別和資料抽取；
- 至少一個預定義 Workflow；
- Workflow 持久狀態；
- MCP 或統一 Tool Adapter；
- 三個 Mock Domain Service；
- 關鍵步驟確認；
- Background Status Checker；
- Visual Sandbox；
- Action Receipt；
- 基本錯誤和人工接管分支。

## 可以簡化

- 使用單一 Backend Process；
- 使用 SQLite；
- 使用簡單 Scheduler；
- Workflow 以 Python／TypeScript state machine 實作；
- MCP Server 可以與 Backend 部署在同一 repository；
- 身份驗證使用模擬 PIN 或確認按鈕；
- Screenshot 可以由前端畫面生成；
- FHIR 只需使用類似 FHIR 的資料格式；
- 人工接管可以是管理員頁面的任務佇列。

## 不應在 10 天內實作

- 完整 BPMN Designer；
- Kubernetes；
- 微服務拆分；
- 真實政府 API；
- 真實電子身份；
- 完整 OAuth delegation；
- 完整 FHIR Server；
- 多 Agent 自主協商；
- 複雜向量資料庫；
- 通用 RPA 系統；
- 完整醫療臨床功能；
- 真實緊急報警功能。

------

# 13. 實作優先級

## P0：必須完成

1. 主醫療改期 Workflow。
2. Task State 持久化。
3. Mock 醫療 API。
4. 使用者確認節點。
5. 模擬提交和狀態追蹤。
6. Visual Sandbox。
7. Action Receipt。

## P1：提高完整度

1. 家屬通知。
2. 一戶通 Mock API。
3. 社福轉介 Mock API。
4. 人工接管工作台。
5. 任務錯誤及重試。
6. 操作截圖。

## P2：時間允許才加入

1. Speech-to-Speech 模式。
2. MCP Inspector 展示。
3. Workflow 視覺化圖。
4. 多語言支援。
5. 更多異常分支。
6. 管理端數據分析。

------

# 14. Demo 成功標準

Demo 至少應證明：

1. 長者不需要知道應使用哪個系統。
2. LLM 能正確將語音需求轉成結構化任務。
3. Workflow 控制實際執行順序。
4. 高風險操作不會在未確認下提交。
5. Ponte 可以調用不同領域的 Mock Service。
6. 任務在等待外部結果期間不會丟失。
7. 外部狀態更新後，Workflow 可以恢復。
8. 每個重要操作都能在畫面上看到。
9. 任務完成後可以生成完整 Action Receipt。
10. 發生異常時可以停止、重試或轉交人工。

------

# 15. 最終架構定位

Ponte Demo 採用：

> **Workflow-first orchestration + Durable Task execution + MCP tool integration + Mock public-service systems**

其中：

- LLM 負責理解和對話；
- Workflow 負責受控執行；
- Durable Task 負責提交後的持續追蹤；
- Policy Layer 負責權限和確認；
- MCP 負責工具標準化；
- Mock Service 負責模擬政府、醫療和社福能力；
- Visual Sandbox 負責讓長者看到執行過程；
- Action Receipt 負責提供可核實的操作憑證；
- Human Handoff 負責處理異常及高風險情況。

此架構不嘗試在 10 天內建成完整公共服務平台，而是以最小可行實作證明 Ponte 的核心價值：

> **長者只需說出需要，系統便能按照受控流程，跨服務完成辦理、持續跟進並提供完整憑證。**

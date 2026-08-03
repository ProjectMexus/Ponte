# Ponte Mock Backends Design

## 目標

根據 `docs/PonteArch.md` 及 `docs/api/` 建立三個可獨立理解、可獨立測試及可替換實作的 mock domain backend：

1. 一戶通 backend，包括文件中的公共服務能力。
2. 醫療 backend，包括 FHIR-inspired 醫療行政預約能力。
3. 社會福利 backend，包括 Arch 文件所描述的服務搜尋、轉介流程及長者文娛活動能力。

這些 backend 只服務本地 Ponte Demo，不連接真實政府、醫療或社福系統，不提供真實身份驗證、醫療判斷、付款或電話撥出。

## 已有文件對接

### 一戶通

實作 `docs/api/one-account-api.md` 的以下 endpoint：

- `POST /mock/one-account/pension/applications`
- `GET /mock/one-account/cash-sharing-plan`
- `POST /mock/one-account/queue-tickets/government-service-center`
- `POST /mock/one-account/queue-tickets/identification-services-bureau`
- `GET /mock/one-account/my/queue-tickets`

### 社會福利 domain 內的長者文娛活動

長者文娛活動 API 使用獨立的 activity service/backend，但按 domain 歸屬放在 social_welfare 資料夾。它實作 `docs/api/elderly-cultural-activities-api.md`：

- `GET /mock/elderly-activities/v1/activities`
- `GET /mock/elderly-activities/v1/activities/{activityId}`
- `GET /mock/elderly-activities/v1/activities/{activityId}/registration-form`
- `POST /mock/elderly-activities/v1/registrations`
- `GET /mock/elderly-activities/v1/registrations/{registrationId}`
- `POST /mock/elderly-activities/v1/phone-registration-assists`
- `GET /mock/elderly-activities/v1/phone-registration-assists/{assistanceId}`

長者活動 fixture 同時包含 `ORG-A`、`ORG-B`、填表活動及電話報名活動。電話協助建立後的狀態只代表協助任務已建立，不代表機構已確認名額。

### 醫療

實作 `docs/api/jinghu-medical-mock-api.md` 的以下 endpoint：

- `GET /mock/medical/v1/departments`
- `GET /mock/medical/v1/departments/{departmentId}/doctors`
- `GET /mock/medical/v1/registration-slots`
- `POST /mock/medical/v1/registrations`
- `GET /mock/medical/v1/appointment-services`
- `GET /mock/medical/v1/appointment-slots`
- `POST /mock/medical/v1/appointments`
- `GET /mock/medical/v1/appointments`
- `GET /mock/medical/v1/appointments/{appointmentId}`
- `GET /mock/medical/v1/tasks/{taskId}`

醫療 backend 只保存及返回行政掛號、檢查／治療預約和 Task 摘要，不保存病歷或臨床資料。`X-Patient-Id` 是每個病人資料查詢和建立操作的邊界。

### 社會福利

`PonteArch.md` 沒有對應的 `docs/api` 文件，因此社福 referral backend 使用 Arch-derived demo contract，並在程式碼與 README 中標示其來源。實作以下 referral endpoint：

- `GET /mock/social-welfare/services`
- `POST /mock/social-welfare/referrals`
- `GET /mock/social-welfare/referrals/{referralId}`
- `POST /mock/social-welfare/referrals/{referralId}/assign`

資料模型對應 Arch 的 `WelfareService`、`Referral`、`CaseWorker` 和 `ReferralStatus`。建立轉介要求 `X-Mock-User-Id`、資料共享同意及長者明確確認；assign 只模擬社工接手，不發送真實通知。活動與 referral 共屬 social_welfare domain，但使用不同 service、fixture、repository 和 API mount。

## 架構

```text
HTTP server / router
        │
        ├── OneAccountHttpAdapter ── OneAccountService ── Repository interfaces
        ├── MedicalHttpAdapter    ── MedicalService    ── Repository interfaces
        ├── SocialWelfareAdapter  ── SocialWelfareService ─ Repository interfaces
        └── ElderlyActivitiesAdapter ── ElderlyActivitiesService ─ Repository interfaces
                                      │
                                      └── Text-file repository implementation
```

HTTP adapter 只負責路由、headers、JSON 解碼、HTTP status 和 envelope；domain service 負責驗證及業務規則；repository 只負責持久化。每個 domain 放在自己的資料夾，不能直接讀寫其他 domain 的資料文件。

### 共用接口

共用核心提供以下可替換接口：

- `Clock.now() -> datetime`：預設使用 Asia/Macau mock clock，也可在測試中注入固定時間。
- `TextRepository`：以 JSON Lines 格式讀寫 `.txt` 文件，提供 `list`, `get`, `insert`, `replace` 和 `find`，實作以原子替換和程序內 lock 保護簡單並發寫入。
- `IdempotencyRepository`：按 user context、endpoint、key 保存 request body fingerprint 和第一次結果；同 key 同 body 重放原結果，不同 body 返回 `IDEMPOTENCY_KEY_REUSED`。
- `IdGenerator`：為 application、ticket、registration、referral、task 和 receipt 產生可讀 mock ID。
- `DomainError`：攜帶 HTTP status、error code、message、details、retryable，由 HTTP 層轉成統一錯誤 envelope。

Domain service 以 constructor injection 接收 repositories、clock 和 ID generator；日後可用 SQL repository、真實 API client 或 MCP adapter 替換，不需要改動 domain service 的輸入輸出模型。

### Persistence layout

預設資料根目錄為 `data/mock/`，按 domain 分隔：

```text
data/mock/
├── one_account/
│   ├── applications.txt
│   ├── queue_tickets.txt
│   └── idempotency.txt
├── medical/
│   ├── appointments.txt
│   ├── tasks.txt
│   └── idempotency.txt
└── social_welfare/
    ├── referrals.txt
    ├── idempotency.txt
    ├── activity_registrations.txt
    ├── phone_registration_assists.txt
    └── activity_idempotency.txt
```

Fixture、科室、活動和服務目錄屬於程式碼內的只讀 demo data；使用者建立的狀態才寫入上述 `.txt` 文件。啟動參數可覆寫資料根目錄，測試使用 temporary directory。

## HTTP 啟動與 MCP 對接

提供 `python -m mock_backends.server` 啟動單一 HTTP process，預設監聽 `127.0.0.1:8080`，可用 `--host`、`--port` 和 `--data-dir` 覆寫。三個 domain 仍透過獨立 service interface 註冊到 router；日後可把相同 service 包裝成 MCP tools，或讓 MCP server 調用 service interface，而不用讓 MCP 直接操作 txt 文件。

HTTP API 保留文件指定的 path、headers、JSON 欄位和主要 status code。對於文件已定義的 success/error contract，以文件為準；共用實作補充生成 request ID、時間戳和 retryable 欄位。

## 業務規則

- 所有 POST 建立操作都要求相應 mock user context；醫療操作另外要求 `X-Patient-Id`。
- 需要確認的建立操作必須帶 `confirmation` 或 `consent=true`；backend 不替 Workflow 跳過確認。
- 所有 POST 都要求 `Idempotency-Key`，重試不能建立第二個資源。
- 查詢結果按使用者或病人 context 隔離；不存在或不屬於 context 的資源統一回 `404`。
- 活動搜尋只返回 `published` 活動；預設再限制尚未開始、報名期內和有剩餘名額。
- 醫療 slot 成功建立預約後遞減剩餘名額；沒有名額返回 `SLOT_NOT_AVAILABLE`。
- 社福 referral 初始為 `PENDING`，assign 後變為 `ASSIGNED` 並附上 mock case worker。
- 任何非預期 exception 都由 HTTP 層轉為 `500 MOCK_SERVICE_ERROR`，不把 traceback 返回給 client。

## 測試策略

測試分成三層：

1. 共用 core 測試：JSON Lines repository、idempotency、mock clock、錯誤 envelope 和原子更新。
2. domain service 測試：以 in-memory repository 注入，驗證每個 domain 的查詢、建立、隔離、確認、名額和重試規則。
3. HTTP smoke tests：啟動 `ThreadingHTTPServer`，對每個 domain 至少覆蓋一條查詢和一條建立／狀態追蹤流程，確認路由、headers、status 與 JSON response 一致。

測試不依賴真實網絡、真實資料庫或外部服務；所有時間和資料目錄都由測試注入。

## 驗收條件

- 三個 domain backend 位於不同資料夾，能透過清晰 service interface 獨立測試。
- 所有 `docs/api/` endpoint 均有對應可呼叫實作；社福 endpoint 明確標示為 Arch-derived contract。
- 建立操作能寫入 `.txt` 文件，重啟後仍可查詢已建立資料。
- idempotency、context isolation、confirmation/consent、slot quota 和活動報名分支均有測試。
- 一條命令可啟動 demo server，並能以 HTTP 呼叫三個 domain。
- 後續替換 repository 或增加 MCP adapter 時，不需要修改 HTTP route contract 或 domain service 的業務規則。

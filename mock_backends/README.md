# Ponte Mock Backends

這個目錄提供 Ponte Demo 使用的 mock domain backend，依據 [`docs/PonteArch.md`](../docs/PonteArch.md) 和 [`docs/api/`](../docs/api/) 建立。它們不連接真實政府、醫療或社福系統，不代表正式 API，也不執行真實身份驗證、醫療判斷、付款或電話撥出。

完整的 Frontend → Middleware → MCP → Mock Backend Demo 請參考 repository 根目錄的 [README](../README.md)。本文件集中說明 backend layer 的啟動、路徑、domain 結構、持久化和測試方式。

## 啟動

需要 Python 3.13 或以上，不需要安裝第三方套件。在 repository 根目錄執行：

```bash
python3 -m mock_backends.server \
  --host 127.0.0.1 \
  --port 8080 \
  --data-dir data/mock
```

server 會在同一個 process mount 以下 domain：

- One Account：`/mock/one-account`
- Elderly Activities（歸屬 Social Welfare domain）：`/mock/elderly-activities/v1`
- Medical：`/mock/medical/v1`
- Social Welfare referrals：`/mock/social-welfare`

參數預設值為 `127.0.0.1:8080` 和 `data/mock`；可用 `--host`、`--port` 及 `--data-dir` 覆寫。若只想以 temporary directory 啟動：

```bash
python3 -m mock_backends.server \
  --host 127.0.0.1 \
  --port 8080 \
  --data-dir /tmp/ponte-mock-data
```

## 快速示例

啟動 server 後，可以直接呼叫各 domain 的查詢接口：

```bash
curl -H 'X-Mock-User-Id: USR-DEMO-001' \
  'http://127.0.0.1:8080/mock/one-account/cash-sharing-plan?year=2026'

curl 'http://127.0.0.1:8080/mock/elderly-activities/v1/activities?category=reading&available_only=true'

curl 'http://127.0.0.1:8080/mock/medical/v1/departments'

curl 'http://127.0.0.1:8080/mock/social-welfare/services?district=氹仔'
```

建立操作依 API 文件要求提供 `Idempotency-Key`；需要使用者上下文的操作提供 `X-Mock-User-Id`，醫療資料操作另外提供 `X-Patient-Id`。需要確認的提交會驗證 `confirmation` 或 `consent=true`，不會由 backend 替 Workflow 跳過確認。

各 domain 的完整 request／response contract：

- [一戶通 API](../docs/api/one-account-api.md)
- [鏡湖通醫療 Mock API](../docs/api/jinghu-medical-mock-api.md)
- [長者文娛活動 API](../docs/api/elderly-cultural-activities-api.md)
- [Social Welfare Arch-derived contract](social_welfare/README.md)

## Domain 結構

```text
mock_backends/
├── core/              Clock、錯誤、JSON envelope、Repository、Idempotency
├── one_account/       養老金、現金分享、政府／身份證明局取籌
├── medical/           FHIR-inspired 掛號、檢查／治療預約、Task
└── social_welfare/    referral 及 ElderlyActivitiesService
```

每個 domain 都有獨立的 service、fixture、contract 和 HTTP adapter。service 使用 constructor injection 接收 repository interface，因此 MCP adapter 應直接調用 domain service，而不是直接讀寫文字檔或把業務邏輯放進 HTTP handler。

共用的 backend 基礎能力位於 `core/`：

- `clock.py`：Asia/Macau mock clock，可在測試中注入固定時間。
- `contracts.py`、`http.py`：domain service 與 HTTP router 之間的共用 contract。
- `errors.py`：一致的錯誤 envelope 和 domain error。
- `persistence.py`：JSON Lines text repository。
- `idempotency.py`：建立操作的 idempotency state。

## 持久化

使用 `--data-dir` 指定資料根目錄。建立的 mock state 會以 JSON Lines 格式保存於 `.txt` 文件：

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
    ├── activity_registrations.txt
    ├── phone_registration_assists.txt
    ├── idempotency.txt
    └── activity_idempotency.txt
```

這是 Demo 的簡化持久化媒介，不適合生產環境；更換為 SQL 或真正外部 API 時，只需替換 repository／client wiring，domain service 和 MCP tool contract 可以保留。完整 stack runner 預設使用 temporary data directory，退出時會清理；需要保留資料時請在根目錄使用 `python3 scripts/run_stack.py --data-dir data/mock`。

## 測試

執行 backend 的單元、domain、HTTP smoke 和 persistence tests：

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q mock_backends tests
```

若只想執行 backend 相關測試：

```bash
python3 -m unittest \
  tests.core.test_core_helpers \
  tests.core.test_idempotency \
  tests.core.test_persistence \
  tests.medical.test_medical_backend \
  tests.one_account.test_one_account_backend \
  tests.social_welfare.test_activity_backend \
  tests.social_welfare.test_social_welfare_backend \
  tests.test_http_smoke \
  tests.test_persistence_restart \
  -v
```

HTTP smoke tests 會啟動 localhost socket；在受限環境中需要允許本地測試 socket。測試使用 temporary directory，不會寫入正式的 `data/mock`。

## 邊界

這些 backend 只模擬服務目錄、資料查詢、建立操作、狀態追蹤和確認規則。它們不提供真實身份驗證、臨床判斷、付款、通知、電話撥出或政府服務提交；所有 fixture、使用者、病人、活動、籌號和回執均為測試資料。

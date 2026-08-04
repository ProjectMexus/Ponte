# Ponte Mock Backends

這是一組供 Ponte Demo 使用的 mock domain backend，依據 `docs/PonteArch.md` 和 `docs/api/` 建立。它們不連接真實政府、醫療或社福系統，不代表正式 API，也不執行真實身份驗證、醫療判斷、付款或電話撥出。

## 完整 Demo 啟動與測試

要驗證 `Frontend → Middleware → MCPServer → Mock Backend`，在 repo 根目錄執行：

```bash
python3 scripts/run_stack.py
```

runner 會依序啟動 mock backend、middleware、middleware 管理的 MCP stdio server，以及 frontend。看到 ready 訊息後開啟它列出的 Frontend URL，輸入：

```text
我想查詢醫療預約
```

按「送出」，成功時畫面會顯示已連線、`selecting_service` 狀態，以及 `medical.get_my_appointments` 和 `medical.list_appointment_services` 兩個 tool event。按 `Ctrl-C` 會反向關閉三個服務，middleware 也會清理 MCP 子程序。

若需要分開除錯，可依序在三個 terminal 執行：

```bash
python3 -m mock_backends.server --host 127.0.0.1 --port 8080 --data-dir /tmp/ponte-mock-data
python3 -m middleware.server --host 127.0.0.1 --port 8090
python3 -m frontend.server --host 127.0.0.1 --port 5173
```

## 啟動

需要 Python 3.11 或以上，不需要第三方依賴：

```bash
python -m mock_backends.server --host 127.0.0.1 --port 8080 --data-dir data/mock
```

預設會在同一個 process mount 三個 domain：

- One Account：`/mock/one-account`
- Elderly Activities（歸屬 Social Welfare domain）：`/mock/elderly-activities/v1`
- Medical：`/mock/medical/v1`
- Social Welfare referrals：`/mock/social-welfare`

## 快速示例

```bash
curl -H 'X-Mock-User-Id: USR-DEMO-001' \
  'http://127.0.0.1:8080/mock/one-account/cash-sharing-plan?year=2026'

curl 'http://127.0.0.1:8080/mock/elderly-activities/v1/activities?category=reading&available_only=true'

curl 'http://127.0.0.1:8080/mock/medical/v1/departments'

curl 'http://127.0.0.1:8080/mock/social-welfare/services?district=氹仔'
```

建立操作依 API 文件要求提供 `Idempotency-Key`；需要使用者上下文的操作提供 `X-Mock-User-Id`，醫療資料操作另外提供 `X-Patient-Id`。需要確認的提交會驗證 `confirmation` 或 `consent=true`，不會由 backend 替 Workflow 跳過確認。

## Domain 結構

```text
mock_backends/
├── core/              # Clock、錯誤、JSON envelope、Repository、Idempotency
├── one_account/       # 養老金、現金分享、政府／身份證明局取籌
├── medical/           # FHIR-inspired 掛號、檢查／治療預約、Task
└── social_welfare/    # referral 及 ElderlyActivitiesService
```

每個 domain 都有獨立 service、fixture 和 HTTP adapter。service 使用 constructor injection 接收 repository interface，因此未來 MCP adapter 應直接調用 domain service，而不是直接讀寫文字檔或把業務邏輯放進 HTTP handler。

主要接口文件：

- [一戶通 API](docs/api/one-account-api.md)
- [鏡湖通醫療 Mock API](docs/api/jinghu-medical-mock-api.md)
- [長者文娛活動 API](docs/api/elderly-cultural-activities-api.md)
- [Social Welfare Arch-derived contract](mock_backends/social_welfare/README.md)

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

這是 Demo 的簡化持久化媒介，不適合生產環境；更換為 SQL 或真正外部 API 時，只需替換 repository/client wiring，domain service 和 MCP tool contract 可以保留。

## 測試

```bash
python -m unittest discover -s tests -v
python -m compileall -q mock_backends tests
```

HTTP smoke tests 會啟動 localhost socket；在受限環境中需要允許本地測試 socket。測試使用 temporary directory，不會寫入正式的 `data/mock`。

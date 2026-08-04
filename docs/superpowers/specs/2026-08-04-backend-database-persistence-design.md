# Backend Database Persistence Design

> 狀態：已確認，供 implementation plan 使用

## 目標

讓 Ponte mock backend 的可變狀態預設持久化到 repository root 下、與 `mock_backends/` 同級的 `database/`，並確保 backend 重啟後仍能讀取及建立 medical 預約。

## 背景與根因

目前 `mock_backends/server.py` 已經把 production repositories wiring 到 `JsonLinesTextRepository`，但 `scripts/run_stack.py` 在未指定 `--data-dir` 時會建立 `TemporaryDirectory`，stack 結束後整個資料目錄被刪除，因此使用者看不到 `.txt` 文件。

另外，production wiring 共用 process-local `SequentialIdGenerator`。新 application instance 會重新從零開始，導致已存在 `APT-0001` 或 `TASK-0001` 時，重啟後的 medical POST 在寫入 repository 前發生 duplicate ID error 並回傳 500。

## 設計

### 資料目錄

production default data root 為 repository root 的 `database/`：

```text
Ponte/
├── mock_backends/
├── database/
│   ├── id_sequences.txt
│   ├── one_account/
│   │   ├── applications.txt
│   │   ├── queue_tickets.txt
│   │   └── idempotency.txt
│   ├── medical/
│   │   ├── appointments.txt
│   │   ├── tasks.txt
│   │   └── idempotency.txt
│   └── social_welfare/
│       ├── referrals.txt
│       ├── idempotency.txt
│       ├── activity_registrations.txt
│       ├── phone_registration_assists.txt
│       └── activity_idempotency.txt
```

`JsonLinesTextRepository` 仍以 JSON Lines 格式寫入 `.txt`，只持久化使用者建立的 mock state；fixtures/catalog 保持程式碼內的唯讀資料。`--data-dir` 仍可覆寫 default，測試繼續注入 temporary directory。

`database/.gitkeep` 只保留資料根目錄；實際 `.txt` 檔案由第一次寫入時建立，避免把本機 mock state 提交到 repository。

### ID 生成

新增 core-level `TextFileIdGenerator`，實作既有 `IdGenerator` interface。它接收一個 `RecordRepository`，按 prefix 在 `id_sequences.txt` 保存目前 sequence。production server 將同一個 generator 注入所有 domain service；service 不依賴具體檔案路徑。

每次 `next(prefix)` 都在 generator 的 process-local lock 內讀取及更新該 prefix 的 sequence，並透過 repository 寫回。重啟後 generator 從 `id_sequences.txt` 恢復，因此不會重新產生已使用的 readable ID。sequence 允許因驗證失敗或 process 中斷產生間隙，但不會重用 ID。

單元測試仍使用 `SequentialIdGenerator`，保持 domain service 測試 deterministic；production persistence 行為由 application-level restart test 覆蓋。

### 啟動 wiring

- `mock_backends.server` 的 CLI default `--data-dir` 改為 repository-root `database/`。
- `scripts.run_stack.run_stack()` 未指定 `data_dir` 時使用 repository-root `database/`，並建立目錄；指定時維持目前的 explicit override 行為。
- `create_application(data_dir)` 使用 `data_dir/id_sequences.txt` 建立 `TextFileIdGenerator`，並將它注入 One Account、Medical、Social Welfare 和 Elderly Activities services。

### 資料流與邊界

```text
HTTP / MCP
    → Backend adapter
    → Domain service
    → RecordRepository / IdempotencyStore / IdGenerator interfaces
    → server wiring 的 JsonLinesTextRepository
    → database/**/*.txt
```

HTTP adapter 和 domain service 不直接組合 database path。資料目錄只由 application factory／CLI 負責，維持 domain 與 storage implementation 解耦。

### 錯誤處理

持久化讀寫錯誤沿用現有 backend 的 shared `MOCK_SERVICE_ERROR` envelope，不暴露 traceback 或本地路徑。ID sequence 更新失敗時不應回傳看似成功的建立 response；既有 exception handling 會將其轉成 500。

## 測試策略

1. 新增 core ID generator test：第一次 generator 寫入 sequence，第二個 generator instance 從同一個 `.txt` repository 繼續產生下一個 ID。
2. 擴充 application restart test：第一個 application 建立 medical registration，確認 `database/medical/appointments.txt`、`tasks.txt` 及 `idempotency.txt` 存在；第二個 application 能讀回第一筆並成功建立另一種 medical appointment，且 appointment/task IDs 不重複。
3. 新增 runner default path test，確認未提供 `data_dir` 時 command 使用 repository-root `database/`，明確 data-dir 仍原樣傳遞。
4. 執行 medical、core、restart、HTTP smoke 及完整 unittest suites；socket-based suite 在 sandbox 不允許時使用受控權限重新執行。

## 驗收條件

- 直接執行 `python3 scripts/run_stack.py` 後，medical 建立操作的 `.txt` 文件位於 `Ponte/database/medical/`。
- stack 重啟後，既有 medical 預約可查詢，新的 medical 預約可建立。
- 不同 domain 的 `.txt` 文件仍分開保存。
- domain service 不新增對 `Path` 或 database layout 的依賴。
- README、mock backend 架構文件及 medical API 文件都說明 default database path、可覆寫方式與 JSON Lines `.txt` 格式。

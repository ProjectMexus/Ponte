# Ponte 公共服務平台 Demo

Ponte 是一個面向長者的公共服務入口與任務執行 Demo。使用者可以用文字或瀏覽器語音表達需要，Ponte 再透過受控的 interaction flow、MCP tools 和 mock domain services 完成服務查詢及後續操作展示。

這個 repository 是本地可執行的 Demo，不連接真實政府、醫療或社福系統，也不代表正式 API；所有身份、醫療、活動、籌號、回執及持久化資料都是 mock。

## 目前 Demo 範圍

- 前端提供適合長者閱讀的對話介面、文字輸入、瀏覽器語音輸入及流程狀態展示。
- Middleware 是前端唯一需要呼叫的 HTTP bridge，負責 interaction controller、session state 和 MCP process 管理。
- MCP 轉接層以 stdio JSON-RPC 暴露固定的 21 個工具，將受控 tool call 轉為 mock backend HTTP request。
- Mock backends 目前包含一戶通、醫療、社會福利及長者文娛活動 domain。
- 目前前端自然語言端到端流程支援「我想查詢自己的醫療預約」的唯讀預約查詢，以及「我想預約醫療服務」的預約流程；預約時會查詢服務、日期範圍和可預約時段，確認後寫入 mock backend，之後可再查詢讀回記錄。其他 domain 可透過 MCP／API contract 和診斷接口測試。

## 架構

```text
瀏覽器
  │ 文字／語音
  ▼
frontend/                 靜態 UI
  ▼ HTTP
middleware/              Interaction Controller + session + execution pipeline
  ▼ stdio JSON-RPC
MCP/                     固定 tool registry + REST adapter
  ▼ HTTP
mock_backends/           One Account / Medical / Social Welfare
```

各層的責任是分開的：LLM 或 intent recognizer 不直接寫入 backend；流程、確認及 tool permission 由 middleware／workflow layer 控制；MCP 只負責受控的工具接入；mock backend 只模擬下游服務。

## 快速開始

需要 Python 3.13 或以上，不需要安裝第三方 Python 或 frontend runtime dependency。

第一次使用可建立本地設定檔：

```bash
cp .env.example .env
```

要使用 Gemini 做 LLM intent recognition，請在本地 `.env` 填入 Google AI Studio API key。`.env.example` 已示範 Ponte 所需的 OpenAI-compatible endpoint `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions` 及低成本模型 `gemini-2.5-flash-lite`；API key 只放在本地設定，不要提交到 repository。若 `PONTE_LLM_API_URL` 留空，middleware 會只使用 keyword intent recognition。

在 repository 根目錄執行完整 stack：

```bash
python3 scripts/run_stack.py
```

Runner 會啟動 mock backend、middleware、middleware 管理的 MCP stdio server 及 frontend，並使用 temporary data directory。看到 `Ponte stack is ready.` 後，開啟它列出的 Frontend URL，輸入以下唯讀查詢：

```text
我想查詢自己的醫療預約
```

成功時畫面會顯示 middleware 已連線、完成狀態，以及只讀的 `medical.get_my_appointments` tool event；這個查詢不會載入服務、不會搜尋時段，也不會建立預約。

要測試醫療預約流程，輸入：

```text
我想預約醫療服務
```

前端會先取得可預約服務；選擇服務及日期範圍後，middleware 會呼叫 `medical.search_appointment_slots` 並返回可預約時段。選擇時段並明確確認後，mock backend 才會建立預約記錄。完成後再次輸入「我想查詢自己的醫療預約」，即可從 mock backend 讀回剛建立的預約。按 `Ctrl-C` 會關閉整個 stack。

也可以在前端輸入以下兩個只讀需求，直接測試 middleware → MCP → mock backend 的完整路徑：

```text
我想查現金分享計劃
我想找長者文娛活動
```

前者會呼叫 `one_account.get_cash_sharing_plan`，後者會呼叫
`one_account.search_elderly_activities`；回應資料會顯示在同一個服務工作區。

若要逐一測試固定 registry 的 MCP tools，可在同一個文字框輸入：

```text
mcp medical.list_departments {}
mcp one_account.get_cash_sharing_plan {"year":2026}
mcp one_account.search_elderly_activities {"available_only":true}
```

這些命令仍然只經由 middleware；middleware 會重新驗證 tool 和 input，再讓真實 MCP stdio server 呼叫 mock backend。GET tool 會立即執行，POST tool 必須按確認後才會發送。

需要保留 mock state 時，可指定資料目錄：

```bash
python3 scripts/run_stack.py --data-dir data/mock
```

### Terminal logging

`run_stack.py` 會在啟動 backend、middleware/MCP 和 frontend 前載入本地 `.env`；shell 中已存在的同名變數優先。可用 `PONTE_LOG_LEVEL` 控制 terminal logging，預設建議使用 `INFO`：

```bash
PONTE_LOG_LEVEL=INFO python3 scripts/run_stack.py
```

輸出會使用 `[frontend]`、`[middleware]`、`[llm]`、`[mcp]` 和 `[backend]` component prefix，並只顯示安全 metadata，例如 method/path/status、model/endpoint metadata、message character counts、normalized intent、tool name/input keys、outcome 和 latency。提高 log level 也不會啟用 raw LLM content；完整 prompt/response、API key 或其他 credentials，以及 medical payload 都不會寫入 terminal。

若已將 terminal output 保存為 `ponte-terminal.log`，可用以下篩選所有 component：

```bash
rg '\[(frontend|middleware|llm|mcp|backend)\]' ponte-terminal.log
```

## 分開啟動各服務

需要逐層除錯時，可在不同 terminal 依次執行：

```bash
python3 -m mock_backends.server \
  --host 127.0.0.1 --port 8080 --data-dir /tmp/ponte-mock-data

python3 -m middleware.server \
  --host 127.0.0.1 --port 8090

python3 -m frontend.server \
  --host 127.0.0.1 --port 5173
```

然後開啟 [http://127.0.0.1:5173](http://127.0.0.1:5173)。前端預設呼叫 `http://127.0.0.1:8090` 的 middleware；若使用其他 port，可以使用 query override，例如：

```text
http://127.0.0.1:5173/?middleware=http://127.0.0.1:18090
```

## 主要服務與接口

| 服務 | 啟動入口 | 預設位置 | 說明 |
| --- | --- | --- | --- |
| Frontend | `python3 -m frontend.server` | `127.0.0.1:5173` | 對話、語音及服務工作區 |
| Middleware | `python3 -m middleware.server` | `127.0.0.1:8090` | `/api/health`、`/api/interactions/*`、受控 MCP 呼叫 |
| Mock Backend | `python3 -m mock_backends.server` | `127.0.0.1:8080` | One Account、Medical、Social Welfare HTTP mock |
| MCP Server | `python3 -m MCP` | stdio | 固定 tool registry；通常由 middleware 管理 |

Mock backend 的主要路徑包括：

- `/mock/one-account`
- `/mock/medical/v1`
- `/mock/elderly-activities/v1`
- `/mock/social-welfare`

## 測試

執行項目、MCP 及 middleware 測試：

```bash
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s MCP/tests -v
python3 -m unittest discover -s middleware/tests -v
python3 -m compileall -q MCP middleware mock_backends frontend scripts tests
```

測試只使用 localhost、temporary directories 及 mock data，不需要外部服務。HTTP smoke／integration tests 需要環境允許綁定 `127.0.0.1` 的 ephemeral socket。

## Repository 結構

```text
Ponte/
├── frontend/             前端 UI、語音能力及 middleware client
├── middleware/           Interaction Controller、session、execution pipeline
├── MCP/                  MCP stdio server、tool registry、REST adapter
├── mock_backends/        一戶通、醫療、社福 mock domain services
├── scripts/run_stack.py  一次啟動完整本地 Demo
├── tests/                跨模組及 full-stack 測試
└── docs/                 架構、產品、API、spec 及 implementation plans
```

## 文件索引

- [Ponte 系統架構](docs/PonteArch.md)
- [Ponte 產品定位與公共服務平台說明](docs/Ponte公共服務平台.md)
- [Frontend README](frontend/README.md)
- [Middleware README](middleware/README.md)
- [MCP／工具轉接層 README](MCP/README.md)
- [Mock Backends README](mock_backends/README.md)
- [一戶通 Mock API](docs/api/one-account-api.md)
- [鏡湖通醫療 Mock API](docs/api/jinghu-medical-mock-api.md)
- [長者文娛活動 API](docs/api/elderly-cultural-activities-api.md)
- [Social Welfare contract README](mock_backends/social_welfare/README.md)

## 邊界與安全提醒

Ponte Demo 不執行真實身份驗證、醫療判斷、付款、電話撥出或政府服務提交。需要確認的操作必須由上層流程提供 `confirmation`／`consent`；adapter 不會自行跳過確認，也不應把這套 mock contract 當成正式服務 API。

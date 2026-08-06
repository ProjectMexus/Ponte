<div align="center">
  <img src="ponte2.jpg" alt="Ponte 語音服務助理小澳" width="180" />

  <h1>Ponte</h1>
  <p><strong>讓長者以自然語言，安心辦理公共服務。</strong></p>
  <p><a href="https://ponte-8k6h.onrender.com/">線上體驗</a> · <a href="docs/PonteArch.md">系統架構</a> · <a href="docs/render-deployment.md">部署說明</a></p>
</div>

Ponte 是一個以粵語／繁體中文為優先的公共服務 Demo。使用者只需說出或輸入需求，系統便會以**受控流程**協調醫療、一戶通和社會福利的模擬服務，清楚展示正在處理的事項、下一步選擇，以及需要確認的操作。

> **立即使用：** [https://ponte-8k6h.onrender.com/](https://ponte-8k6h.onrender.com/)

## 為何是 Ponte？

公共服務不應要求長者先知道該用哪個平台、填哪份表格或記住哪個部門。Ponte 把複雜的服務入口轉化為一段可理解、可追蹤、可隨時確認或停止的對話式流程。

| 使用者看見的體驗 | 系統如何保障流程 |
| --- | --- |
| 以文字或瀏覽器語音說出需要 | 前端提供大字、高對比和語音回讀；語音內容會先顯示，送出後才開始處理。 |
| 清楚看見每項服務的進度 | 每個需求都有獨立任務卡，保留步驟、結果和可執行的下一步。 |
| 在提交前掌握自己將要做的事 | 會造成變更的操作必須經使用者明確確認。 |
| 不必面對原始 API 或工具名稱 | Middleware 以固定的 MCP 工具和預先定義的 workflow 處理整個流程。 |

## 可體驗的服務

- **醫療預約查詢**：讀取模擬的覆診資料，顯示服務、日期、時間、地點和狀態。
- **醫療服務預約**：選擇服務與日期範圍，查看可選時段，確認後建立模擬預約。
- **現金分享計劃**：查詢模擬的一戶通計劃摘要。
- **長者文娛活動**：搜尋可參加的長者活動。

線上版可直接嘗試以下句子：

```text
我想查詢自己的醫療預約
我想預約醫療服務
我想查現金分享計劃
我想找長者文娛活動
```

## 架構一覽

```text
瀏覽器（文字／語音、任務工作區）
                │ HTTP
                ▼
Frontend ──► Middleware（意圖辨識、流程、確認、任務狀態）
                │ stdio JSON-RPC
                ▼
        MCP（固定工具註冊表與 REST adapter）
                │ HTTP
                ▼
Mock Backends（醫療／一戶通／社會福利）
```

這個分層讓 LLM 專注於理解需求和解釋結果，卻不能自行跳過確認、變更任務狀態或直接存取下游服務。實際執行只會經過受控的 workflow 和固定工具註冊表。

## 本機快速開始

### 需求

- Python 3.13 或以上
- 現代瀏覽器；如要使用語音，請允許麥克風權限
- 不需安裝額外的 Python 或前端套件

在專案根目錄建立本機設定檔：

```powershell
Copy-Item .env.example .env
```

macOS／Linux 可使用：

```bash
cp .env.example .env
```

接著啟動完整 Demo：

```bash
python scripts/run_stack.py
```

當終端機顯示 `Ponte stack is ready.` 後，開啟輸出的 Frontend URL（預設為 `http://127.0.0.1:5173/`）。按 `Ctrl-C` 可停止整個 stack。

### 使用 Docker Compose（可選）

```bash
docker compose up --build
```

然後開啟 [http://localhost:5173](http://localhost:5173)。

## 設定 LLM（可選）

未設定 LLM 時，Ponte 仍會以內建的 keyword intent recognition 執行 Demo。若要使用 OpenAI 相容的 chat-completions endpoint，請在本機 `.env` 設定：

```dotenv
PONTE_LLM_API_URL=https://generativelanguage.googleapis.com/v1beta/openai/chat/completions
PONTE_LLM_API_KEY=your-api-key
PONTE_LLM_MODEL=gemini-2.5-flash-lite
```

Task Recovery LLM 使用另一組 `PONTE_TASK_RECOVERY_LLM_*` 設定，只接收已清理的 backend／工具結果來產生復原建議。兩組設定都不應提交到 repository。完整環境變數和行為請參考 [Middleware README](middleware/README.md)。

## 驗證

```bash
python -m unittest discover -s tests -v
python -m unittest discover -s MCP/tests -v
python -m unittest discover -s middleware/tests -v
python -m compileall -q MCP middleware mock_backends frontend scripts tests
```

前端靜態檢查：

```bash
python -m unittest tests.test_frontend_static -v
node --check frontend/app.js
node --check frontend/interaction-view.js
```

## 專案導覽

| 目錄／檔案 | 用途 |
| --- | --- |
| [`frontend/`](frontend/) | 無 build dependency 的語音優先網頁介面與 middleware client。 |
| [`middleware/`](middleware/) | 互動控制器、workflow、確認機制、session 和 MCP process 管理。 |
| [`MCP/`](MCP/) | 固定的工具註冊表、stdio JSON-RPC server 和 REST adapter。 |
| [`mock_backends/`](mock_backends/) | 醫療、一戶通及社會福利的模擬服務。 |
| [`database/`](database/) | 本機 Demo 的 JSON Lines mock state；內容不應提交。 |
| [`scripts/run_stack.py`](scripts/run_stack.py) | 一次啟動 backend、middleware、MCP 和 frontend 的本機 runner。 |
| [`render.yaml`](render.yaml) | Render 單容器部署 Blueprint。 |

更多細節：

- [系統架構與設計原則](docs/PonteArch.md)
- [Ponte 產品定位](docs/Ponte公共服務平台.md)
- [語音 Agent 說明](docs/VOICE_AGENT.md)
- [Render 部署指南](docs/render-deployment.md)
- [Frontend](frontend/README.md) · [Middleware](middleware/README.md) · [MCP](MCP/README.md) · [Mock Backends](mock_backends/README.md)

## Demo 範圍與安全說明

Ponte 是展示用途的本機／雲端 Demo，不會連接真實政府、醫療或社福系統，亦不執行真實身分驗證、診斷、付款、轉介或服務提交。帳戶、預約、活動、回執及所有持久化資料皆為 mock data；請勿輸入真實個人或醫療資料。

即使在 Demo 中，涉及變更的流程仍需明確確認。這個設計用以說明 Ponte 的核心原則：**AI 可以協助操作，但使用者必須看得見、聽得懂，並始終保有確認、修正和停止的權利。**

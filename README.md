<div align="center">
  <img src="background.png" alt="聆澳 Ponte — 聆聽澳門，連結每一段故事" width="100%" />
</div>

<div align="center">
  <h1>Ponte</h1>
  <p><strong>讓長者以自然語言，安心辦理公共服務。</strong></p>
  <p>
    <a href="https://ponte-8k6h.onrender.com/">🌐 線上體驗</a> •
    <a href="docs/PonteArch.md">📐 系統架構</a> •
    <a href="docs/render-deployment.md">🚀 部署說明</a>
  </p>
</div>

Ponte 是一個以粵語與繁體中文為核心的公共服務語音助理原型（Prototype）。使用者只需透過語音或文字輸入需求，系統即會透過**受控工作流（Controlled Workflows）** 協調醫療、一戶通與社會福利等模擬服務，並即時呈現處理進度、後續選項及待確認操作。

> **Live Demo:** [https://ponte-8k6h.onrender.com/](https://ponte-8k6h.onrender.com/)

## 技術棧 (Tech Stack)

| 層級 | 技術 |
| --- | --- |
| **Backend / Middleware** | Python 3.13, Asyncio |
| **AI / Agent Protocol** | Model Context Protocol (MCP), OpenAI-compatible LLM API |
| **Frontend** | Vanilla JS, Web Speech API |
| **Infrastructure** | Docker, JSON-RPC, Render |

## 為何是 Ponte？

公共服務不應要求長者先知道該用哪個平台、填哪份表格或記住哪個部門。Ponte 把複雜的服務入口轉化為一段可理解、可追蹤、且具備高度控制權的對話式流程。

| 使用者體驗 (User Experience) | 系統保障機制 (System Guarantees) |
| --- | --- |
| **多模態輸入** — 文字 / 語音 | 前端支援大字體、高對比與語音報讀；語音轉譯結果經確認後才觸發處理。 |
| **狀態可視化** — 即時進度追蹤 | 採用獨立任務卡（Task Cards）追蹤步驟、結果與可執行的下一步。 |
| **人機協作確認** — Human-in-the-loop | 涉及狀態變更的關鍵操作，強制要求使用者明確確認（Explicit Confirmation）。 |
| **抽象化工具呼叫** — 零 API 暴露 | Middleware 透過預定義的 MCP 工具與標準化工作流封裝底層邏輯。 |

## 可體驗的服務

| 服務 | 說明 |
| --- | --- |
| **醫療預約查詢** | 讀取模擬的覆診資料，顯示服務、日期、時間、地點和狀態。 |
| **醫療服務預約** | 選擇服務與日期範圍，查看可選時段，確認後建立模擬預約。 |
| **現金分享計劃** | 查詢模擬的一戶通計劃摘要。 |
| **長者文娛活動** | 搜尋可參加的長者活動。 |

線上版可直接嘗試以下 Prompts：

```text
我想查詢自己的醫療預約
我想預約醫療服務
我想查現金分享計劃
我想找長者文娛活動
```

## 架構一覽 (Architecture)

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

此分層架構確保 LLM 僅專注於意圖理解與結果解釋，嚴格限制其自行跳過確認步驟、變更任務狀態或直接存取下游服務的權限（Guardrails）。所有實際執行均受限於 Middleware 的受控工作流與 MCP 工具註冊表。

## 快速開始 (Quick Start)

### 環境需求 (Prerequisites)

- Python 3.13+
- 現代瀏覽器（如需使用語音，請允許麥克風權限）
- 無需額外安裝前端或 Python 依賴套件

在專案根目錄建立本機設定檔：

```powershell
# Windows (PowerShell)
Copy-Item .env.example .env
```
```bash
# macOS / Linux
cp .env.example .env
```

啟動完整服務堆疊（Stack）：

```bash
python scripts/run_stack.py
```

當終端機輸出 `Ponte stack is ready.` 後，開啟輸出的 Frontend URL（預設為 `http://127.0.0.1:5173/`）。按 `Ctrl-C` 即可優雅地停止整個 stack。

### 使用 Docker Compose（可選）

```bash
docker compose up --build
```

啟動後，請前往 [http://localhost:5173](http://localhost:5173)。

## 設定 LLM (Configuration)

未設定 LLM 時，Ponte 會以內建的 Keyword Intent Recognition 執行 Demo。若要對接 OpenAI 相容的 `chat/completions` 端點，請於本機 `.env` 設定：

```dotenv
PONTE_LLM_API_URL=https://generativelanguage.googleapis.com/v1beta/openai/chat/completions
PONTE_LLM_API_KEY=your-api-key
PONTE_LLM_MODEL=gemini-2.5-flash-lite
```

**Task Recovery LLM：**
系統另備有一組獨立的 `PONTE_TASK_RECOVERY_LLM_*` 設定。此模型僅接收經清理的後端／工具回傳結果，專門用於產生任務復原建議。

> ⚠️ **請勿將 API Key 等敏感設定提交至版本控制系統。** 完整環境變數與行為規範請參閱 [Middleware README](middleware/README.md)。

## 測試與驗證 (Testing)

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

## 專案導覽 (Project Structure)

| 目錄／檔案 | 用途 |
| --- | --- |
| [`frontend/`](frontend/) | 無 build dependency 的語音優先網頁介面與 middleware client。 |
| [`middleware/`](middleware/) | 互動控制器、workflow、確認機制、session 和 MCP process 管理。 |
| [`MCP/`](MCP/) | 固定的工具註冊表、stdio JSON-RPC server 和 REST adapter。 |
| [`mock_backends/`](mock_backends/) | 醫療、一戶通及社會福利的模擬服務。 |
| [`database/`](database/) | 本機 Demo 的 JSON Lines mock state（⚠️ 不應提交至版本控制）。 |
| [`scripts/run_stack.py`](scripts/run_stack.py) | 一鍵啟動 backend、middleware、MCP 和 frontend 的本機 runner。 |
| [`render.yaml`](render.yaml) | Render 單容器部署 Blueprint。 |

**深入閱讀：**

- [系統架構與設計原則](docs/PonteArch.md)
- [Ponte 產品定位](docs/Ponte公共服務平台.md)
- [語音 Agent 說明](docs/VOICE_AGENT.md)
- [Render 部署指南](docs/render-deployment.md)
- 模組專屬文件：[Frontend](frontend/README.md) · [Middleware](middleware/README.md) · [MCP](MCP/README.md) · [Mock Backends](mock_backends/README.md)

## 免責聲明 (Disclaimer)

Ponte 僅作為展示用途的本機／雲端原型，**不會**連接真實的政府、醫療或社福系統，亦不執行真實的身份驗證、診斷、付款、轉介或服務提交。系統中的所有帳戶、預約、活動及持久化資料皆為 **Mock Data**；請勿輸入真實個人或醫療資料。

即使在 Demo 中，涉及變更的流程仍需明確確認。此設計旨在實踐 Ponte 的核心治理原則：

> **AI 可以輔助操作，但使用者必須「看得見、聽得懂」，並始終保有確認、修正與終止流程的絕對權利。**

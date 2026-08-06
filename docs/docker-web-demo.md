# Ponte Web Demo — Docker 部署

本文件說明如何使用 Docker Compose 在本 worktree 根目錄部署 Ponte web demo。
所有服務都是純 Python 3.13 標準庫（無 pip dependency），前端由 nginx 提供靜態檔案。

## 架構

| Service    | Image / Build           | 容器內埠 | 主機埠       | 職責 |
| ---------- | ----------------------- | -------- | ------------ | ---- |
| backend    | `Dockerfile.middleware` | 8080     | 不公開       | mock_backends HTTP 服務，JSON Lines 持久化於 `/app/database`（named volume `ponte-data`） |
| middleware | `Dockerfile.middleware` | 8090     | `8090:8090`  | `python -m middleware.server`，啟動 MCP stdio child，對外提供 `/api/*` |
| frontend   | `Dockerfile.frontend`   | 80       | `5173:80`    | nginx 靜態 UI + `/api/` 反向代理到 middleware |

### 同源代理（重點）

瀏覽器永遠只使用同源 URL。`frontend/mcp-client.js` 的 `defaultBaseUrl()` 依序檢查：

1. `?middleware=` query parameter；
2. `window.PONTE_MIDDLEWARE_URL`；
3. fallback `""`（同源請求）。

`frontend.nginx.conf` 將 `/api/` 代理到 `http://middleware:8090`，因此 Docker-only
hostname 不會出現在瀏覽器請求中。`http://localhost:8090` 仍會公開，供主機側健康檢查使用。

`/ponte2.jpg`（語音頭像）位於 repository 根目錄，由 nginx 以獨立 location 提供，
與本地 `frontend/server.py` 的行為一致。

## 環境變數

`docker-compose.yml` 已內建安全預設；可在 `.env`（複製 `.env.example`）覆寫：

| 變數 | 預設 | 說明 |
| ---- | ---- | ---- |
| `PONTE_LOG_LEVEL` | `INFO` | `DEBUG` 會輸出 LLM/MCP 內容（含醫療 mock 資料），憑據仍遮罩 |
| `PONTE_PATIENT_ID` | `PAT-DEMO-001` | middleware 固定 demo 身分 |
| `PONTE_MOCK_USER_ID` | `USR-DEMO-001` | 同上 |
| `PONTE_AUTHORIZATION` | `Bearer mock-user-token` | 同上 |
| `PONTE_LLM_API_URL` / `PONTE_LLM_API_KEY` / `PONTE_LLM_MODEL` | 空 | 可選 intent LLM；未設定時使用 `KeywordIntentRecognizer` 確定性 fallback |
| `PONTE_TASK_RECOVERY_LLM_*` | 空 | 可選 task recovery LLM；空 URL 使用確定性 fallback |

`PONTE_BACKEND_URL` 與 `PONTE_FRONTEND_ORIGINS` 由 compose 直接設定
（`http://backend:8080` 與 `http://localhost:5173,http://127.0.0.1:5173`），不需要手動調整。

## 啟動

```powershell
Set-Location "E:\Steph's repos\Ponte\.worktrees\web-demo-deployment"

docker compose config      # 驗證 compose 檔案
docker compose build
docker compose up -d
docker compose ps
```

## 驗證

```powershell
# 前端靜態頁面
Invoke-WebRequest http://localhost:5173

# middleware 健康檢查（經主機公開埠）
Invoke-RestMethod http://localhost:8090/api/health

# 同源代理路徑（經前端容器）
Invoke-RestMethod http://localhost:5173/api/health
```

`/api/health` 回傳 `backend_reachable=true` 代表 middleware → MCP → mock backend 鏈路正常。

### 瀏覽器冒煙測試

1. 開啟 `http://localhost:5173`（不需要 `?middleware=` 參數，同源即可）。
2. 輸入非破壞性查詢：`我想查詢自己的醫療預約`。
3. 預期：intent 識別（無 LLM key 時走 keyword fallback）→ 顯示醫療預約列表。

## 停止與清理

```powershell
docker compose down          # 保留 ponte-data volume（預約等 mock 持久化資料）
docker compose down -v       # 一併刪除持久化資料
```

## 疑難排解

- **埠衝突**：`5173` 或 `8090` 被佔用時（例如本機 `python scripts/run_stack.py` 仍在執行），
  先停止本機 stack，或修改 `docker-compose.yml` 的 `ports` 左側主機埠。
- **health check 失敗**：`docker compose logs --no-color middleware` 檢查
  `PONTE_BACKEND_URL` 是否指向 `http://backend:8080`。
- **語音功能**：未設定 `PONTE_VOICE_STT_*` 時 voice turn 回傳 503，屬預期行為；文字互動不受影響。

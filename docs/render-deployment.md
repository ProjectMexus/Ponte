# Ponte Web Demo — Render 部署

本文件說明如何將 Ponte web demo 部署到 [Render](https://render.com)。

## 架構

使用**單一 Docker 容器**同時執行三個進程：
- **nginx**（port 80）— 靜態 UI + `/api/` 反向代理到 middleware
- **middleware**（port 8090）— `python -m middleware.server`，啟動 MCP stdio child
- **backend**（port 8080）— `python -m mock_backends.server`，JSON Lines 持久化於 `/app/database`

瀏覽器永遠使用同源 URL（Render 分配的 `.onrender.com` 網址），nginx 代理 `/api/` 到 localhost:8090。

## 部署方式

### 方式 A：Render Blueprint（推薦）

1. 將此 repository 推送到 GitHub。
2. 前往 [Render Blueprint Deploy](https://dashboard.render.com/blueprint/deploy)。
3. 選擇此 repository 的 GitHub 連線。
4. Render 會讀取 `render.yaml` 並建立服務。
5. 部署完成後，更新 `PONTE_FRONTEND_ORIGINS` 環境變數為實際的 Render URL（例如 `https://ponte-web-demo.onrender.com`）。

### 方式 B：手動建立 Web Service

1. 登入 [Render Dashboard](https://dashboard.render.com)。
2. 點擊 **New** → **Web Service**。
3. 連線 GitHub repository，選擇此 repo。
4. 設定：
   - **Name**: `ponte-web-demo`（或自訂）
   - **Runtime**: `Docker`
   - **Dockerfile Path**: `./Dockerfile.render`
   - **Docker Context**: `.`
5. 環境變數（在 **Environment** 分頁設定）：
   | Key | Value |
   | --- | --- |
   | `PONTE_BACKEND_URL` | `http://127.0.0.1:8080` |
   | `PONTE_FRONTEND_ORIGINS` | `https://<your-service>.onrender.com`（部署後更新） |
   | `PONTE_LOG_LEVEL` | `INFO` |
   | `PONTE_PATIENT_ID` | `PAT-DEMO-001` |
   | `PONTE_MOCK_USER_ID` | `USR-DEMO-001` |
   | `PONTE_AUTHORIZATION` | `Bearer mock-user-token` |
   | `PONTE_LLM_API_URL` | （可選，留空使用 keyword fallback） |
   | `PONTE_LLM_API_KEY` | （可選） |
   | `PONTE_LLM_MODEL` | （可選） |
6. **Disk**（持久化）：
   - 點擊 **Add Disk**。
   - **Name**: `ponte-data`
   - **Mount Path**: `/app/database`
   - **Size**: 1 GB（足夠 demo 使用）
7. 點擊 **Create Web Service**。

## 驗證

部署完成後：

```powershell
# 前端頁面
Invoke-WebRequest https://<your-service>.onrender.com

# 健康檢查（經同源代理）
Invoke-RestMethod https://<your-service>.onrender.com/api/health

# 瀏覽器冒煙測試
# 開啟 https://<your-service>.onrender.com
# 輸入：我想查詢自己的醫療預約
```

`/api/health` 應回傳 `{"status":"ok","backend_reachable":true,"tool_count":21,...}`。

## 環境變數說明

| 變數 | 預設 | 說明 |
| ---- | ---- | ---- |
| `PONTE_BACKEND_URL` | `http://127.0.0.1:8080` | 容器內 backend 位址（勿修改） |
| `PONTE_FRONTEND_ORIGINS` | （需設定） | 瀏覽器來源 URL，用於 CORS；設定為 Render 分配的 URL |
| `PONTE_LOG_LEVEL` | `INFO` | `DEBUG` 會輸出 LLM/MCP 內容（含醫療 mock 資料） |
| `PONTE_PATIENT_ID` | `PAT-DEMO-001` | middleware 固定 demo 身分 |
| `PONTE_MOCK_USER_ID` | `USR-DEMO-001` | 同上 |
| `PONTE_AUTHORIZATION` | `Bearer mock-user-token` | 同上 |
| `PONTE_LLM_API_URL` | 空 | 可選 intent LLM；未設定時使用 `KeywordIntentRecognizer` |
| `PONTE_LLM_API_KEY` | 空 | 同上 |
| `PONTE_LLM_MODEL` | 空 | 同上 |

## 持久化

Render Disk 提供 `/app/database` 目錄的持久化。mock backend 的 JSON Lines 檔案（預約、任務、ID 序列）會寫入此目錄，重啟後保留。

**注意**：Render Disk 是單實例附加，不支援多實例同時寫入。若需要水平擴展，應改用外部資料庫。

## 疑難排解

- **CORS 錯誤**：確認 `PONTE_FRONTEND_ORIGINS` 設定為實際的 Render URL（包含 `https://`）。
- **Health check 失敗**：檢查 Render 的 **Logs** 分頁，確認 backend/middleware/nginx 都成功啟動。
- **502 Bad Gateway**：nginx 無法連線 middleware；檢查 middleware 是否崩潰（查看 logs）。
- **持久化資料遺失**：確認已設定 Render Disk 並掛載到 `/app/database`。

## 本機測試 Render 映像

在推送前，可先在本機測試 Render 映像：

```powershell
Set-Location "E:\Steph's repos\Ponte\.worktrees\web-demo-deployment"
docker build -f Dockerfile.render -t ponte-render .
docker run --rm -p 5173:80 -e PONTE_FRONTEND_ORIGINS=http://localhost:5173 ponte-render
```

開啟 `http://localhost:5173` 驗證。

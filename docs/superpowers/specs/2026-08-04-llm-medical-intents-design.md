# LLM 醫療查詢與預約流程設計

## 目標

讓 Ponte 使用 OpenAI-compatible LLM intent recognizer，清楚分辨兩種醫療需求：

- 查詢目前使用者自己的醫療預約。
- 預約醫療服務，並查詢可用服務及時段後完成確認。

預約資料必須透過既有 MCP 與 mock backend 寫入保存；之後再次查詢時，必須從 backend 讀回該預約，而不是只依賴 session memory。

## 現有背景

- `middleware/intent.py` 已有 LLM recognizer、keyword fallback 及 OpenAI-compatible chat-completions 呼叫。
- `.env` 已設定 Gemini OpenAI-compatible endpoint、`gemini-2.5-flash-lite` 及本地 API key；API key 不會寫入 repository。
- `mock_backends/medical` 已支援：
  - `medical.list_appointment_services`
  - `medical.search_appointment_slots`
  - `medical.create_appointment`
  - `medical.get_my_appointments`
  - `medical.get_task_status`
- 現有 controller 將所有醫療 intent 混合到同一條「查詢預約及服務」流程，前端 action button 尚未提供服務、日期和時段 payload。

## 設計

### 1. Intent contract

把 canonical intent 擴展為：

- `medical_query`：查詢自己的既有醫療預約、日期、狀態或預約紀錄。
- `medical_booking`：想預約醫療服務，或為了預約而查詢服務、醫生及可預約時段。
- 保留 `cash_sharing`、`elderly_activity` 及 `general`。

LLM system prompt 必須要求只返回 JSON object，並清楚列出兩個醫療 intent 的邊界。`LlmIntentRecognizer._normalize_intent` 支援上述 canonical values 及必要的舊 alias；不支援的 intent 仍會觸發 hybrid recognizer 的 keyword fallback。

Keyword recognizer 作為無 LLM、LLM 錯誤或回應格式錯誤時的 fallback。包含「可預約時段」、「預約服務」的請求優先分類為 `medical_booking`；包含「我的預約」、「已有預約」、「預約紀錄」且沒有預約動作的請求分類為 `medical_query`。

`IntentDecision` 提供 `is_medical_query` 和 `is_medical_booking` properties；`is_medical` 保留作為向後兼容的總醫療判斷。

### 2. 查詢自己的預約

controller 收到 `medical_query` 後只執行：

```text
medical.get_my_appointments
```

成功時將資料放到 `state.data["appointments"]`，設定：

- `task_state = "completed"`
- `current_step = "load_appointments"`
- 不提供預約操作 action

每次查詢都呼叫 backend，因此預約完成後，以新 session 或同一 session 再查詢，都能取得 mock backend 已保存的記錄。查詢失敗沿用既有安全錯誤與 retry boundary。

### 3. 預約醫療服務與可用時段

`medical_booking` 沿用既有受控流程：

```text
medical.list_appointment_services
  → search_slots action
  → medical.search_appointment_slots
  → select_slot action
  → confirm action
  → medical.create_appointment
  → medical.get_task_status
```

`medical.create_appointment` 只會在明確 confirm action 後執行，並維持既有 `consent: true`、patient context 和 idempotency key。既有 `medical.search_appointment_slots` API 繼續負責按服務及日期範圍返回可用時段，不新增或繞過 backend contract。

### 4. 前端操作

保留 middleware 的 action API，並讓前端根據 response data 和 current step 產生可用操作：

- `selecting_service`：顯示服務選擇，以及日期起訖欄位；送出 `search_slots` 時帶上 `service_id`、`date_from`、`date_to`。
- `selecting_slot`：顯示 backend 返回的可用時段；選擇後送出 `select_slot` 及 `slot_id`。
- `awaiting_confirmation`：顯示已選時段和確認／取消操作。

查詢流程只顯示預約資料，不顯示 booking actions。前端不直接呼叫 mock backend，也不自行拼接 tool URL。

### 5. 測試與驗收

新增或更新以下測試：

- intent unit tests：LLM prompt／response 可解析 `medical_query` 和 `medical_booking`；keyword fallback 可分辨「查詢我的預約」與「查詢可預約時段」。
- controller unit tests：`medical_query` 只呼叫 `medical.get_my_appointments`；`medical_booking` 保留服務、時段、確認和 task status 流程。
- middleware/backend integration：完成一次服務選擇、時段搜尋、確認預約，驗證 `medical.create_appointment` 已呼叫並返回 task；其後以另一個 session 查詢，驗證 `appointments` 包含已建立的預約。
- frontend static tests：保留既有靜態資源檢查，並覆蓋新操作需要的 data attributes 或 renderer contract。

測試不得依賴真實 Gemini 網路或暴露 API key；LLM 呼叫以 fake transport／注入 recognizer 測試，完整 stack 測試使用 deterministic recognizer 或 keyword fallback。實際執行時若 Gemini 不可用，仍自動 fallback 到 keyword recognizer。

## 錯誤處理與邊界

- LLM 缺少設定、HTTP 錯誤、timeout、回應 JSON 不合法或 intent 不支援時，沿用 hybrid fallback，不讓外部錯誤阻斷服務。
- 查詢 backend 失敗時不得回傳空資料冒充成功，應保留既有錯誤結構與 retry action 行為。
- 預約建立前必須有 confirmation；取消時不得出現 `medical.create_appointment` tool event。
- mock backend 只保存醫療行政預約資料，不新增臨床判斷或真實醫療能力。
- 不把 API key、病人 context 或完整原始 LLM response 加入 browser response 或 repository。

## 非目標

- 不改動既有 medical backend endpoint schema。
- 不讓 LLM 直接決定任意 tool、URL、HTTP method 或 headers。
- 不讓 LLM 自動跳過日期、時段選擇或使用者確認。
- 不加入 durable session store、真實身份驗證或真實醫療服務串接。

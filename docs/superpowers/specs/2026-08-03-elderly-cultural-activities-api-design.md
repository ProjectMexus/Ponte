# 長者文娛活動 Mock API 設計說明

## 目的

為 Ponte Demo 建立一個獨立的長者文娛活動 Mock API，展示 Agent 能夠：

1. 理解長者對活動類型、日期、地區、年齡、語言及報名方式的需求。
2. 搜尋不同機構提供的近期、有效且仍可參加的活動。
3. 向長者解釋活動資訊及報名方式。
4. 對填表活動收集必要資料並提交 mock 報名。
5. 對電話報名活動建立電話報名協助任務，而不假稱已經撥出電話或完成官方報名。
6. 持續查詢報名狀態並產生可供 Demo UI 顯示的回執。

## 設計範圍

- 新增獨立文檔：`docs/api/elderly-cultural-activities-api.md`。
- API 根路徑為 `/mock/elderly-activities/v1`。
- 內置兩個 mock 機構：`ORG-A`、`ORG-B`。
- 支援講座、展覽、工作坊、課程、閱讀活動、表演及社區活動等類型。
- 列表預設只返回活動狀態有效、尚未開始、仍在報名期內及有剩餘名額的活動。
- 報名方式至少包括 `form` 和 `phone`，兩者在 fixture 中都要出現。

## 非目標

- 不連接澳門政府、社福機構或公共圖書館的真實報名系統。
- 不執行真實身份驗證、真實付款或真實電話撥出。
- 不把官方網站的活動資料當作實時同步資料；本 API 的活動、名額、聯絡資料均為 mock。
- 不由 LLM 直接決定或跳過提交確認；提交操作由 Ponte Workflow 控制。

## 核心 endpoint

| Endpoint | 用途 | 建議風險 |
| --- | --- | --- |
| `GET /activities` | 按長者需求搜尋跨機構活動 | `R0` |
| `GET /activities/{activityId}` | 取得單一活動完整資料 | `R0` |
| `GET /activities/{activityId}/registration-form` | 取得填表活動的欄位 schema | `R1` |
| `POST /registrations` | 提交填表活動的 mock 報名 | `R2` |
| `GET /registrations/{registrationId}` | 查詢填表報名狀態 | `R1` |
| `POST /phone-registration-assists` | 建立電話報名協助任務 | `R2` |
| `GET /phone-registration-assists/{assistanceId}` | 查詢電話協助任務狀態 | `R1` |

## 資料與工作流決策

### 活動搜尋

Agent 將自然語言需求轉換為 API query parameters。例如「我想下星期在氹仔參加閱讀活動，最好可以打電話報名」可轉換為：

```text
GET /activities?date_from=2026-08-10&date_to=2026-08-16&district=氹仔&category=reading&registration_method=phone&available_only=true
```

API 負責資料過濾和排序；Agent 負責理解語意、比較結果及用長者容易理解的方式說明。

### 報名分支

```text
搜尋活動
  ├─ registration.method=form
  │    ├─ 取得 registration-form
  │    ├─ 向長者收集欄位
  │    ├─ 顯示摘要並取得確認
  │    └─ POST registrations
  └─ registration.method=phone
       ├─ 顯示電話、服務時間和參加條件
       ├─ 準備通話提示
       ├─ 顯示摘要並取得確認
       └─ POST phone-registration-assists
```

只有 `POST` 返回成功結果後，Agent 才可以聲稱表格已提交或電話協助任務已建立。電話協助的狀態必須清楚標記為等待人工／Agent 撥號，不得標記為已完成報名。

### Arch 對接

API 是 Mock Service Layer；身份、確認、Durable Task、重試及 Action Receipt 由 Ponte Workflow Orchestrator 管理。建議由活動 MCP Adapter 暴露：

```text
one_account.search_elderly_activities
one_account.get_elderly_activity
one_account.get_activity_registration_form
one_account.submit_activity_registration
one_account.start_phone_registration_assistance
one_account.get_activity_registration_status
```

## 來源及資料建模依據

活動資料欄位參考澳門特區長者服務資訊網文化藝術活動頁常見的活動名稱、地點、日期／時間、對象／名額和聯絡電話；活動類型則參考澳門公共圖書館長者活動頁的活動分類及活動時間表。來源只用於決定 mock 資料形狀，並不代表本 API 與官方系統有任何正式整合。

- [澳門特區長者服務資訊網：文化藝術](https://www.ageing.ias.gov.mo/cn/index.php/event/art)
- [澳門公共圖書館：活動類型（長者／成人）](https://www.library.gov.mo/zh-hant/elder/event/type-of-activity)
- [澳門公共圖書館：活動時間表](https://www.library.gov.mo/zh-hant/promotion-events/activity-schedule)

## 驗收條件

- API 文檔是獨立文件，且沒有修改既有 `docs/api/one-account-api.md`。
- 文檔包含 `ORG-A` 和 `ORG-B` 的分開列表示例。
- 每個列表至少有一項填表活動和一項電話活動。
- 每項活動均有活動類型、名稱、摘要、日期／時間、地點、對象／名額、費用、可參加狀態及報名方式。
- 填表活動有可讀的表格 schema、提交 request、成功 response 和錯誤例子。
- 電話活動有電話、服務時間、通話提示、協助任務 request 和「未代表完成報名」的狀態說明。
- 文檔說明 Agent 搜尋、確認、提交及追蹤的端到端流程。
- 文檔標明所有資料和結果都是 mock，不可當作官方實時資料。

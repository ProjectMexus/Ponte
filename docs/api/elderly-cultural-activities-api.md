# Mock 長者文娛活動 API 文檔

> 版本：`v1`  
> 更新日期：`2026-08-03`  
> API 類型：Demo / Mock  
> 對應架構：`docs/PonteArch.md` 的 Mock Service Layer、Workflow Orchestrator 及 Action Receipt

本 API 專門供 Ponte Demo 模擬長者文娛活動搜索及報名協助。它不連接澳門政府、社福機構或公共圖書館的真實系統，不執行真實身份驗證、不撥出真實電話，也不代表任何官方 API 規格。所有機構、活動、名額、聯絡資料、報名結果及回執均為 mock 資料。

API 的 Demo 目標是讓 Agent 完成以下流程：

```text
長者自然語言需求
  → 搜尋 A、B 等不同機構的活動
  → 按活動類型、日期、地區、名額和報名方式比較
  → 解釋活動詳情及參加方法
  → 填表提交，或建立電話報名協助任務
  → 查詢狀態並展示回執
```

活動欄位形狀參考澳門特區長者服務資訊網文化藝術活動頁提供的活動名稱、地點、日期／時間、對象／名額及聯絡電話；活動類型和活動時間表參考澳門公共圖書館長者活動頁。這些官方頁面只作資料建模參考，並非本 API 的資料來源或實時同步來源。

- [澳門特區長者服務資訊網：文化藝術](https://www.ageing.ias.gov.mo/cn/index.php/event/art)
- [澳門公共圖書館：活動類型（長者／成人）](https://www.library.gov.mo/zh-hant/elder/event/type-of-activity)
- [澳門公共圖書館：活動時間表](https://www.library.gov.mo/zh-hant/promotion-events/activity-schedule)

---

## 1. API 基本規範

### 1.1 Base URL

```text
/mock/elderly-activities/v1
```

例如：

```http
GET /mock/elderly-activities/v1/activities?organization_id=ORG-A&available_only=true
```

### 1.2 Content Type

所有 request body 使用 `application/json`，所有 response 使用 `application/json`。

### 1.3 Headers

| Header | 查詢 | POST | 說明 |
| --- | --- | --- | --- |
| `X-Mock-User-Id` | 否 | 是 | Mock 使用者上下文，例如 `USR-DEMO-001`；不是正式身份驗證。 |
| `X-Request-Id` | 否 | 否 | 呼叫方指定的請求 ID；未提供時由 API 生成。 |
| `Idempotency-Key` | 不適用 | 是 | 防止 Agent 重試時重複提交，例如 `TASK-3821-ACTIVITY-REG-01`。 |
| `Content-Type` | 否 | 是 | 必須為 `application/json`。 |

`X-Mock-User-Id` 只用於把 mock 報名和 Demo 使用者關聯，不代表已完成一戶通登入或長者身份驗證。

相同 `X-Mock-User-Id`、endpoint 和 `Idempotency-Key` 重複使用時，API 返回第一次提交的結果；如果 request body 不同，返回 `409 IDEMPOTENCY_KEY_REUSED`。

### 1.4 日期、時間及時區

- 日期使用 `YYYY-MM-DD`，例如 `2026-08-15`。
- 時間使用 ISO 8601，時區固定為澳門時間 `+08:00`，例如 `2026-08-15T14:00:00+08:00`。
- API 使用 mock clock；本文檔示例的 `mock_now` 為 `2026-08-03T09:00:00+08:00`。
- 「最近有效可參加」預設表示：活動尚未開始、活動狀態為 `published`、報名狀態為 `open`，以及 `remaining > 0`。

### 1.5 統一 response envelope

成功回應：

```json
{
  "request_id": "REQ-20260803-0001",
  "data": {}
}
```

錯誤回應：

```json
{
  "request_id": "REQ-20260803-0002",
  "error": {
    "code": "ACTIVITY_NOT_FOUND",
    "message": "找不到指定的活動，或活動已不再公開。",
    "details": {
      "activity_id": "ACT-UNKNOWN"
    },
    "retryable": false,
    "timestamp": "2026-08-03T09:01:02+08:00"
  }
}
```

### 1.6 常用 HTTP 狀態碼

| Status | 使用情況 |
| --- | --- |
| `200 OK` | 查詢成功或重放已成功處理的 idempotent request |
| `201 Created` | 成功建立填表報名 |
| `202 Accepted` | 成功建立電話報名協助任務，等待 Agent／人工撥號 |
| `400 Bad Request` | JSON 格式或 query parameter 不正確 |
| `401 Unauthorized` | POST 缺少 `X-Mock-User-Id` 或 mock context 無效 |
| `404 Not Found` | 找不到活動、報名或電話協助任務 |
| `409 Conflict` | 活動已滿、報名方式不適用或 idempotency key 衝突 |
| `422 Unprocessable Entity` | 欄位格式正確，但未符合活動報名條件 |
| `500 Internal Server Error` | 模擬服務未預期錯誤，可由 Workflow 重試 |

---

## 2. 資料列舉

### 2.1 活動類型

| `activity_type` | `category` | 長者易懂的顯示名稱 |
| --- | --- | --- |
| `lecture` | `learning` | 講座 |
| `workshop` | `arts` 或 `learning` | 工作坊 |
| `course` | `learning` | 課程 |
| `exhibition` | `arts` 或 `reading` | 展覽 |
| `reading_group` | `reading` | 閱讀／分享會 |
| `performance` | `arts` | 表演／音樂會 |
| `screening` | `arts` | 放映會 |
| `community_activity` | `community` | 社區活動 |
| `other` | `other` | 其他活動 |

`category` 是給 Agent 做較寬鬆的需求匹配；`activity_type` 是活動的主要展示類型。

### 2.2 活動及報名狀態

| 欄位 | 值 | 說明 |
| --- | --- | --- |
| `activity.status` | `published`、`cancelled` | 是否公開及仍可展示 |
| `availability.status` | `open`、`full`、`closed` | 是否可以繼續報名 |
| `registration.method` | `form`、`phone` | 參加者需要採用的方式 |
| `registration.status` | `open`、`closed`、`not_started` | 報名時間窗口狀態 |
| `registration_result.status` | `confirmed`、`submitted`、`waitlisted`、`rejected` | 填表報名結果 |
| `phone_assistance.status` | `ready_for_call`、`waiting_for_phone_call`、`completed`、`failed` | 電話協助任務結果；`completed` 只表示協助流程完成，不自動代表機構已確認名額 |

---

## 3. 搜尋活動

### `GET /activities`

跨 A、B 機構搜索符合長者需求的活動。Agent 可以先使用關鍵字或類型查詢，再用地區、日期及報名方式縮小結果。

#### Query parameters

| 欄位 | 必填 | 類型 | 說明 |
| --- | --- | --- | --- |
| `keyword` | 否 | string | 搜尋活動名稱、摘要、標籤、機構名稱，例如 `閱讀`、`唱歌`。 |
| `organization_id` | 否 | string | `ORG-A` 或 `ORG-B`；不傳時搜索所有 mock 機構。 |
| `activity_type` | 否 | string | 逗號分隔，例如 `workshop,performance`。 |
| `category` | 否 | string | 逗號分隔，例如 `arts,reading`。 |
| `date_from` | 否 | date | 活動開始日期下限；未提供時使用 mock today。 |
| `date_to` | 否 | date | 活動開始日期上限。 |
| `district` | 否 | string | 澳門地區，例如 `澳門半島`、`氹仔`。 |
| `participant_age` | 否 | integer | 用於檢查活動的年齡條件，例如 `72`。 |
| `registration_method` | 否 | enum | `form` 或 `phone`。 |
| `accessibility` | 否 | string | 需要的支援，逗號分隔，例如 `wheelchair,cantonese`。 |
| `available_only` | 否 | boolean | 預設 `true`；只返回仍有名額及在報名期內的活動。 |
| `sort` | 否 | enum | `start_at_asc`、`registration_deadline_asc`；預設 `start_at_asc`。 |
| `page` | 否 | integer | 預設 `1`。 |
| `page_size` | 否 | integer | 預設 `20`，最大 `100`。 |

即使 `available_only=false`，API 仍只返回 `status=published` 的活動，不會返回已取消或未公開資料。

#### Request：搜索所有機構的近期活動

```http
GET /mock/elderly-activities/v1/activities?keyword=閱讀&date_from=2026-08-03&date_to=2026-08-31&available_only=true&sort=start_at_asc
X-Request-Id: REQ-20260803-0003
```

#### Response `200 OK`

```json
{
  "request_id": "REQ-20260803-0003",
  "data": {
    "activities": [
      {
        "activity_id": "ACT-ORG-B-20260809-001",
        "organization": {
          "organization_id": "ORG-B",
          "name": "B機構社區圖書館",
          "short_name": "B機構",
          "contact_phone": "+853-6200-2001"
        },
        "title": "樂齡閱讀小組：澳門故事",
        "summary": "以澳門人物和社區故事為主題的輕鬆閱讀及分享活動。",
        "activity_type": "reading_group",
        "category": "reading",
        "tags": ["閱讀", "分享", "社區"],
        "schedule": {
          "start_at": "2026-08-09T10:30:00+08:00",
          "end_at": "2026-08-09T12:00:00+08:00",
          "timezone": "Asia/Macau"
        },
        "venue": {
          "name": "B機構中央圖書館多功能室",
          "address": "澳門半島閱讀街 8 號",
          "district": "澳門半島"
        },
        "audience": {
          "age_min": 55,
          "age_max": null,
          "description": "55歲或以上長者及對閱讀有興趣人士",
          "quota": 20
        },
        "fee": {
          "amount": 0,
          "currency": "MOP",
          "display": "全免"
        },
        "availability": {
          "status": "open",
          "quota": 20,
          "registered": 12,
          "remaining": 8
        },
        "registration": {
          "method": "form",
          "status": "open",
          "opens_at": "2026-07-20T09:00:00+08:00",
          "closes_at": "2026-08-07T18:00:00+08:00",
          "deadline": "2026-08-07",
          "form_id": "FORM-ORG-B-READING-001",
          "requires_confirmation": true
        },
        "participation": {
          "languages": ["粵語", "普通話"],
          "accessibility": ["wheelchair_accessible"],
          "what_to_bring": "可自備一本想分享的書籍，非必須。"
        },
        "last_updated_at": "2026-08-02T16:00:00+08:00"
      }
    ],
    "meta": {
      "mock_now": "2026-08-03T09:00:00+08:00",
      "total": 1,
      "page": 1,
      "page_size": 20,
      "has_next": false,
      "search_scope": "all_organizations",
      "filters_applied": ["keyword", "date_from", "date_to", "available_only"]
    }
  }
}
```

---

## 4. A 機構最近有效可參加活動列表

### Request

```http
GET /mock/elderly-activities/v1/activities?organization_id=ORG-A&available_only=true&sort=start_at_asc
X-Request-Id: REQ-20260803-0010
```

### Response `200 OK`

```json
{
  "request_id": "REQ-20260803-0010",
  "data": {
    "organization": {
      "organization_id": "ORG-A",
      "name": "A機構長者文化中心",
      "short_name": "A機構",
      "contact_phone": "+853-6200-1001",
      "service_hours": "星期一至五 09:00-12:00、14:00-17:30"
    },
    "activities": [
      {
        "activity_id": "ACT-ORG-A-20260808-001",
        "title": "樂齡粵曲欣賞與唱腔體驗",
        "summary": "由導師介紹粵曲基本唱腔，並安排簡單合唱體驗。",
        "activity_type": "workshop",
        "category": "arts",
        "tags": ["粵曲", "音樂", "唱歌"],
        "schedule": {
          "start_at": "2026-08-08T14:30:00+08:00",
          "end_at": "2026-08-08T16:00:00+08:00",
          "timezone": "Asia/Macau"
        },
        "venue": {
          "name": "A機構文化活動室",
          "address": "澳門半島福樂街 12 號 2 樓",
          "district": "澳門半島"
        },
        "audience": {
          "age_min": 55,
          "age_max": null,
          "description": "55歲或以上長者，無需音樂經驗",
          "quota": 30
        },
        "fee": {"amount": 0, "currency": "MOP", "display": "全免"},
        "availability": {
          "status": "open",
          "quota": 30,
          "registered": 18,
          "remaining": 12
        },
        "registration": {
          "method": "form",
          "status": "open",
          "opens_at": "2026-07-15T09:00:00+08:00",
          "closes_at": "2026-08-06T17:30:00+08:00",
          "deadline": "2026-08-06",
          "form_id": "FORM-ORG-A-CANTONESE-001",
          "requires_confirmation": true
        },
        "participation": {
          "languages": ["粵語"],
          "accessibility": ["wheelchair_accessible", "seated_activity"],
          "what_to_bring": "無需攜帶樂器。"
        },
        "last_updated_at": "2026-08-02T10:00:00+08:00"
      },
      {
        "activity_id": "ACT-ORG-A-20260815-002",
        "title": "手機攝影與生活記錄工作坊",
        "summary": "學習用手機拍攝日常照片及簡單整理相簿。",
        "activity_type": "workshop",
        "category": "arts",
        "tags": ["手機", "攝影", "數碼技能"],
        "schedule": {
          "start_at": "2026-08-15T10:00:00+08:00",
          "end_at": "2026-08-15T12:00:00+08:00",
          "timezone": "Asia/Macau"
        },
        "venue": {
          "name": "A機構氹仔活動室",
          "address": "氹仔海濱大馬路 20 號",
          "district": "氹仔"
        },
        "audience": {
          "age_min": 60,
          "age_max": null,
          "description": "60歲或以上長者，每人請自備可用智能手機",
          "quota": 16
        },
        "fee": {"amount": 20, "currency": "MOP", "display": "澳門元20元"},
        "availability": {
          "status": "open",
          "quota": 16,
          "registered": 8,
          "remaining": 8
        },
        "registration": {
          "method": "phone",
          "status": "open",
          "opens_at": "2026-07-20T09:00:00+08:00",
          "closes_at": "2026-08-12T17:30:00+08:00",
          "deadline": "2026-08-12",
          "phone": "+853-6200-1001",
          "phone_hours": "星期一至五 09:00-12:00、14:00-17:30",
          "required_information": ["姓名", "聯絡電話", "年齡", "是否需要輪椅位置"],
          "requires_confirmation": true
        },
        "participation": {
          "languages": ["粵語", "普通話"],
          "accessibility": ["wheelchair_accessible", "large_print_handout"],
          "what_to_bring": "請攜帶已充電的智能手機。"
        },
        "last_updated_at": "2026-08-01T15:30:00+08:00"
      },
      {
        "activity_id": "ACT-ORG-A-20260822-003",
        "title": "長者健康生活分享講座",
        "summary": "以日常作息、社區運動及興趣生活為主題的非醫療健康分享。",
        "activity_type": "lecture",
        "category": "wellness",
        "tags": ["生活", "健康", "分享"],
        "schedule": {
          "start_at": "2026-08-22T15:00:00+08:00",
          "end_at": "2026-08-22T16:30:00+08:00",
          "timezone": "Asia/Macau"
        },
        "venue": {
          "name": "A機構長者禮堂",
          "address": "澳門半島福樂街 12 號 1 樓",
          "district": "澳門半島"
        },
        "audience": {
          "age_min": 55,
          "age_max": null,
          "description": "55歲或以上長者",
          "quota": 50
        },
        "fee": {"amount": 0, "currency": "MOP", "display": "全免"},
        "availability": {
          "status": "open",
          "quota": 50,
          "registered": 31,
          "remaining": 19
        },
        "registration": {
          "method": "form",
          "status": "open",
          "opens_at": "2026-07-25T09:00:00+08:00",
          "closes_at": "2026-08-20T17:30:00+08:00",
          "deadline": "2026-08-20",
          "form_id": "FORM-ORG-A-WELLNESS-001",
          "requires_confirmation": true
        },
        "participation": {
          "languages": ["粵語"],
          "accessibility": ["wheelchair_accessible", "seated_activity"],
          "what_to_bring": "可自備飲用水。"
        },
        "last_updated_at": "2026-08-02T09:30:00+08:00"
      }
    ],
    "meta": {
      "mock_now": "2026-08-03T09:00:00+08:00",
      "total": 3,
      "page": 1,
      "page_size": 20,
      "has_next": false,
      "default_filter": "published + registration.open + remaining > 0 + start_at >= mock_now"
    }
  }
}
```

---

## 5. B 機構最近有效可參加活動列表

### Request

```http
GET /mock/elderly-activities/v1/activities?organization_id=ORG-B&available_only=true&sort=start_at_asc
X-Request-Id: REQ-20260803-0011
```

### Response `200 OK`

```json
{
  "request_id": "REQ-20260803-0011",
  "data": {
    "organization": {
      "organization_id": "ORG-B",
      "name": "B機構社區圖書館",
      "short_name": "B機構",
      "contact_phone": "+853-6200-2001",
      "service_hours": "星期一至日 10:00-19:00，公眾假期除外"
    },
    "activities": [
      {
        "activity_id": "ACT-ORG-B-20260809-001",
        "title": "樂齡閱讀小組：澳門故事",
        "summary": "以澳門人物和社區故事為主題的輕鬆閱讀及分享活動。",
        "activity_type": "reading_group",
        "category": "reading",
        "tags": ["閱讀", "分享", "社區"],
        "schedule": {
          "start_at": "2026-08-09T10:30:00+08:00",
          "end_at": "2026-08-09T12:00:00+08:00",
          "timezone": "Asia/Macau"
        },
        "venue": {
          "name": "B機構中央圖書館多功能室",
          "address": "澳門半島閱讀街 8 號",
          "district": "澳門半島"
        },
        "audience": {
          "age_min": 55,
          "age_max": null,
          "description": "55歲或以上長者及對閱讀有興趣人士",
          "quota": 20
        },
        "fee": {"amount": 0, "currency": "MOP", "display": "全免"},
        "availability": {
          "status": "open",
          "quota": 20,
          "registered": 12,
          "remaining": 8
        },
        "registration": {
          "method": "form",
          "status": "open",
          "opens_at": "2026-07-20T09:00:00+08:00",
          "closes_at": "2026-08-07T18:00:00+08:00",
          "deadline": "2026-08-07",
          "form_id": "FORM-ORG-B-READING-001",
          "requires_confirmation": true
        },
        "participation": {
          "languages": ["粵語", "普通話"],
          "accessibility": ["wheelchair_accessible"],
          "what_to_bring": "可自備一本想分享的書籍，非必須。"
        },
        "last_updated_at": "2026-08-02T16:00:00+08:00"
      },
      {
        "activity_id": "ACT-ORG-B-20260816-002",
        "title": "公共圖書館 e 學堂：手機應用入門",
        "summary": "示範手機基本設定、通訊軟件及公共服務網站的常用操作。",
        "activity_type": "course",
        "category": "learning",
        "tags": ["手機", "數碼技能", "學堂"],
        "schedule": {
          "start_at": "2026-08-16T14:00:00+08:00",
          "end_at": "2026-08-16T16:00:00+08:00",
          "timezone": "Asia/Macau"
        },
        "venue": {
          "name": "B機構何東圖書館電腦室",
          "address": "澳門半島高士德大馬路 13 號",
          "district": "澳門半島"
        },
        "audience": {
          "age_min": 60,
          "age_max": null,
          "description": "60歲或以上長者，初學者優先",
          "quota": 12
        },
        "fee": {"amount": 0, "currency": "MOP", "display": "全免"},
        "availability": {
          "status": "open",
          "quota": 12,
          "registered": 7,
          "remaining": 5
        },
        "registration": {
          "method": "phone",
          "status": "open",
          "opens_at": "2026-07-25T10:00:00+08:00",
          "closes_at": "2026-08-13T19:00:00+08:00",
          "deadline": "2026-08-13",
          "phone": "+853-6200-2001",
          "phone_hours": "星期一至日 10:00-19:00，公眾假期除外",
          "required_information": ["姓名", "聯絡電話", "年齡", "是否持有圖書館讀者證"],
          "requires_confirmation": true
        },
        "participation": {
          "languages": ["粵語", "普通話"],
          "accessibility": ["wheelchair_accessible", "large_print_handout"],
          "what_to_bring": "請攜帶自己的智能手機；如有圖書館讀者證也可一併帶備。"
        },
        "last_updated_at": "2026-08-02T11:00:00+08:00"
      },
      {
        "activity_id": "ACT-ORG-B-20260823-003",
        "title": "館藏展覽導賞：澳門城市記憶",
        "summary": "由館員帶領參觀主題展覽，介紹館藏圖片、書籍及社區記憶。",
        "activity_type": "exhibition",
        "category": "reading",
        "tags": ["展覽", "導賞", "澳門故事"],
        "schedule": {
          "start_at": "2026-08-23T11:00:00+08:00",
          "end_at": "2026-08-23T12:30:00+08:00",
          "timezone": "Asia/Macau"
        },
        "venue": {
          "name": "B機構中央圖書館展覽廳",
          "address": "澳門半島閱讀街 8 號 1 樓",
          "district": "澳門半島"
        },
        "audience": {
          "age_min": 55,
          "age_max": null,
          "description": "長者及成人，適合對本地文化有興趣人士",
          "quota": 25
        },
        "fee": {"amount": 0, "currency": "MOP", "display": "全免"},
        "availability": {
          "status": "open",
          "quota": 25,
          "registered": 9,
          "remaining": 16
        },
        "registration": {
          "method": "form",
          "status": "open",
          "opens_at": "2026-07-28T10:00:00+08:00",
          "closes_at": "2026-08-20T19:00:00+08:00",
          "deadline": "2026-08-20",
          "form_id": "FORM-ORG-B-EXHIBITION-001",
          "requires_confirmation": true
        },
        "participation": {
          "languages": ["粵語"],
          "accessibility": ["wheelchair_accessible", "seated_breaks"],
          "what_to_bring": "無需特別準備。"
        },
        "last_updated_at": "2026-08-02T14:00:00+08:00"
      }
    ],
    "meta": {
      "mock_now": "2026-08-03T09:00:00+08:00",
      "total": 3,
      "page": 1,
      "page_size": 20,
      "has_next": false,
      "default_filter": "published + registration.open + remaining > 0 + start_at >= mock_now"
    }
  }
}
```

---

## 6. 查詢單一活動詳情

### `GET /activities/{activityId}`

返回列表摘要以外的完整活動資料。Agent 在向長者推薦前，應先查詢詳情確認報名期限、年齡要求、費用、地點和所需參加資料。

#### Request

```http
GET /mock/elderly-activities/v1/activities/ACT-ORG-A-20260815-002
X-Request-Id: REQ-20260803-0020
```

#### Response `200 OK`

```json
{
  "request_id": "REQ-20260803-0020",
  "data": {
    "activity_id": "ACT-ORG-A-20260815-002",
    "status": "published",
    "organization": {
      "organization_id": "ORG-A",
      "name": "A機構長者文化中心",
      "short_name": "A機構",
      "contact_phone": "+853-6200-1001",
      "service_hours": "星期一至五 09:00-12:00、14:00-17:30"
    },
    "title": "手機攝影與生活記錄工作坊",
    "summary": "學習用手機拍攝日常照片及簡單整理相簿。",
    "description": "導師會用簡單步驟示範構圖、拍攝及相簿分類，參加者可即場練習。",
    "activity_type": "workshop",
    "category": "arts",
    "tags": ["手機", "攝影", "數碼技能"],
    "schedule": {
      "start_at": "2026-08-15T10:00:00+08:00",
      "end_at": "2026-08-15T12:00:00+08:00",
      "timezone": "Asia/Macau"
    },
    "venue": {
      "name": "A機構氹仔活動室",
      "address": "氹仔海濱大馬路 20 號",
      "district": "氹仔",
      "transport_note": "近氹仔市中心巴士站，場地設升降機。"
    },
    "audience": {
      "age_min": 60,
      "age_max": null,
      "description": "60歲或以上長者，每人請自備可用智能手機",
      "quota": 16
    },
    "fee": {"amount": 20, "currency": "MOP", "display": "澳門元20元"},
    "availability": {
      "status": "open",
      "quota": 16,
      "registered": 8,
      "remaining": 8,
      "last_checked_at": "2026-08-03T09:00:00+08:00"
    },
    "participation": {
      "languages": ["粵語", "普通話"],
      "accessibility": ["wheelchair_accessible", "large_print_handout"],
      "what_to_bring": "請攜帶已充電的智能手機。"
    },
    "registration": {
      "method": "phone",
      "status": "open",
      "opens_at": "2026-07-20T09:00:00+08:00",
      "closes_at": "2026-08-12T17:30:00+08:00",
      "deadline": "2026-08-12",
      "phone": "+853-6200-1001",
      "phone_hours": "星期一至五 09:00-12:00、14:00-17:30",
      "required_information": ["姓名", "聯絡電話", "年齡", "是否需要輪椅位置"],
      "requires_confirmation": true,
      "instructions": [
        "於服務時間致電 A機構。",
        "說明活動名稱及日期。",
        "提供姓名、聯絡電話和年齡。",
        "向職員確認是否成功留位及活動費付款方法。"
      ]
    },
    "last_updated_at": "2026-08-01T15:30:00+08:00"
  }
}
```

`404 ACTIVITY_NOT_FOUND` 表示活動不存在、已取消或不再對當前 mock context 公開。

---

## 7. 取得填表活動的表格 schema

### `GET /activities/{activityId}/registration-form`

只有 `registration.method=form` 的活動支援此 endpoint。Agent 使用返回的 `fields` 逐項向長者提問，不應自行猜測必填資料。

#### Request

```http
GET /mock/elderly-activities/v1/activities/ACT-ORG-A-20260808-001/registration-form
X-Mock-User-Id: USR-DEMO-001
X-Request-Id: REQ-20260803-0030
```

#### Response `200 OK`

```json
{
  "request_id": "REQ-20260803-0030",
  "data": {
    "activity_id": "ACT-ORG-A-20260808-001",
    "form_id": "FORM-ORG-A-CANTONESE-001",
    "method": "form",
    "title": "樂齡粵曲欣賞與唱腔體驗報名表",
    "requires_confirmation": true,
    "fields": [
      {
        "name": "full_name",
        "label": "姓名",
        "type": "string",
        "required": true,
        "sensitive": false
      },
      {
        "name": "phone",
        "label": "聯絡電話",
        "type": "phone",
        "required": true,
        "sensitive": true
      },
      {
        "name": "age",
        "label": "年齡",
        "type": "integer",
        "required": true,
        "minimum": 55,
        "sensitive": true
      },
      {
        "name": "accessibility_needs",
        "label": "需要的場地支援",
        "type": "enum[]",
        "required": false,
        "options": ["wheelchair_space", "seated_activity", "none"],
        "sensitive": false
      },
      {
        "name": "emergency_contact_name",
        "label": "緊急聯絡人姓名",
        "type": "string",
        "required": false,
        "sensitive": true
      },
      {
        "name": "emergency_contact_phone",
        "label": "緊急聯絡人電話",
        "type": "phone",
        "required": false,
        "sensitive": true
      }
    ],
    "consents": [
      {
        "name": "personal_data",
        "label": "同意 A機構只為本活動報名使用上述資料",
        "required": true
      }
    ],
    "submission": {
      "method": "POST",
      "path": "/mock/elderly-activities/v1/registrations"
    }
  }
}
```

如果活動是電話報名，API 返回：

```json
{
  "request_id": "REQ-20260803-0031",
  "error": {
    "code": "PHONE_REGISTRATION_REQUIRED",
    "message": "此活動需要致電機構報名，沒有線上填表 schema。",
    "details": {
      "activity_id": "ACT-ORG-A-20260815-002",
      "phone": "+853-6200-1001",
      "phone_hours": "星期一至五 09:00-12:00、14:00-17:30"
    },
    "retryable": false,
    "timestamp": "2026-08-03T09:02:00+08:00"
  }
}
```

---

## 8. 提交填表活動報名

### `POST /registrations`

建立填表活動的 mock 報名。此為 `R2` 操作，Ponte Workflow 必須在提交前展示活動、時間、地點、費用、參加者資料及資料使用同意，並取得長者明確確認。

#### Request headers

```http
POST /mock/elderly-activities/v1/registrations
X-Mock-User-Id: USR-DEMO-001
X-Request-Id: REQ-20260803-0040
Idempotency-Key: TASK-3821-ACTIVITY-REG-01
Content-Type: application/json
```

#### Request body

```json
{
  "activity_id": "ACT-ORG-A-20260808-001",
  "form_id": "FORM-ORG-A-CANTONESE-001",
  "participant": {
    "full_name": "陳美玲",
    "phone": "+853-6234-5678",
    "age": 80,
    "accessibility_needs": ["seated_activity"],
    "emergency_contact_name": "陳家明",
    "emergency_contact_phone": "+853-6288-1122"
  },
  "consents": {
    "personal_data": true
  },
  "confirmation": {
    "confirmation_id": "CONF-20260803-0040",
    "confirmed_at": "2026-08-03T09:05:20+08:00",
    "displayed_summary_hash": "sha256:mock-activity-summary-001"
  }
}
```

#### Input 欄位

| 欄位 | 類型 | 必填 | 說明 |
| --- | --- | --- | --- |
| `activity_id` | string | 是 | 必須是仍可報名的活動。 |
| `form_id` | string | 是 | 必須與活動目前的表格 schema 相同。 |
| `participant.full_name` | string | 是 | 參加者姓名。 |
| `participant.phone` | string | 是 | 參加者聯絡電話。 |
| `participant.age` | integer | 視表格 | 必須符合活動 `age_min`／`age_max`。 |
| `participant.accessibility_needs` | string[] | 否 | 只可提交 schema 中列出的支援。 |
| `participant.emergency_contact_name` | string | 視表格 | 表格要求時必填。 |
| `participant.emergency_contact_phone` | string | 視表格 | 表格要求時必填。 |
| `consents.personal_data` | boolean | 是 | 必須為 `true`。 |
| `confirmation` | object | 是 | Ponte Workflow 的明確確認記錄。 |

#### Response `201 Created`

```json
{
  "request_id": "REQ-20260803-0040",
  "data": {
    "registration": {
      "registration_id": "REG-20260803-0001",
      "activity_id": "ACT-ORG-A-20260808-001",
      "method": "form",
      "status": "confirmed",
      "participant": {
        "display_name": "陳美玲",
        "phone_masked": "+853-****-5678"
      },
      "submitted_at": "2026-08-03T09:05:25+08:00",
      "next_action": {
        "type": "ATTEND_ACTIVITY",
        "message": "請於 2026-08-08 14:15 到 A機構文化活動室報到。"
      }
    },
    "receipt": {
      "receipt_id": "REC-20260803-0040",
      "official_reference": "ORG-A-MOCK-88219",
      "issued_at": "2026-08-03T09:05:26+08:00",
      "display_message": "A機構已收到你的活動報名。"
    },
    "task": {
      "task_id": "TASK-20260803-0040",
      "workflow_type": "elderly_activity_form_registration_v1",
      "status": "completed",
      "current_step": "complete"
    }
  }
}
```

#### 可能錯誤

| HTTP | `error.code` | 說明 |
| --- | --- | --- |
| `401` | `MOCK_USER_REQUIRED` | 缺少 `X-Mock-User-Id`。 |
| `409` | `ACTIVITY_FULL` | 提交時已沒有剩餘名額。 |
| `409` | `PHONE_REGISTRATION_REQUIRED` | 活動不接受線上表格，必須使用電話報名。 |
| `409` | `DUPLICATE_ACTIVITY_REGISTRATION` | 同一 mock 使用者已報名同一活動。 |
| `409` | `IDEMPOTENCY_KEY_REUSED` | 相同 key 被用於不同 request body。 |
| `422` | `FORM_VERSION_MISMATCH` | `form_id` 不是活動目前版本。 |
| `422` | `MISSING_REQUIRED_FIELD` | 缺少表格 schema 要求的資料。 |
| `422` | `AGE_REQUIREMENT_NOT_MET` | 參加者年齡不符合活動條件。 |
| `422` | `CONSENT_REQUIRED` | 沒有同意個人資料使用。 |
| `422` | `CONFIRMATION_REQUIRED` | 沒有 Ponte Workflow 的明確確認記錄。 |

---

## 9. 查詢填表報名狀態

### `GET /registrations/{registrationId}`

#### Request

```http
GET /mock/elderly-activities/v1/registrations/REG-20260803-0001
X-Mock-User-Id: USR-DEMO-001
X-Request-Id: REQ-20260803-0050
```

#### Response `200 OK`

```json
{
  "request_id": "REQ-20260803-0050",
  "data": {
    "registration_id": "REG-20260803-0001",
    "activity_id": "ACT-ORG-A-20260808-001",
    "activity_title": "樂齡粵曲欣賞與唱腔體驗",
    "organization_id": "ORG-A",
    "method": "form",
    "status": "confirmed",
    "participant": {
      "display_name": "陳美玲",
      "phone_masked": "+853-****-5678"
    },
    "submitted_at": "2026-08-03T09:05:25+08:00",
    "updated_at": "2026-08-03T09:05:26+08:00",
    "receipt_reference": "ORG-A-MOCK-88219",
    "events": [
      {
        "event_type": "form_validated",
        "timestamp": "2026-08-03T09:05:25+08:00"
      },
      {
        "event_type": "registration_confirmed",
        "timestamp": "2026-08-03T09:05:26+08:00"
      }
    ]
  }
}
```

若報名不屬於當前 `X-Mock-User-Id`，API 返回 `404 REGISTRATION_NOT_FOUND`，避免暴露其他 mock 使用者的報名資料。

---

## 10. 建立電話報名協助任務

### `POST /phone-registration-assists`

對 `registration.method=phone` 的活動建立一份可追蹤的協助任務。此 endpoint 不會代表 Agent 已撥出電話，也不會把活動名額標記為已確認；它只保存長者已確認的通話準備資料，供 Demo UI 展示下一步。

#### Request headers

```http
POST /mock/elderly-activities/v1/phone-registration-assists
X-Mock-User-Id: USR-DEMO-001
X-Request-Id: REQ-20260803-0060
Idempotency-Key: TASK-3821-ACTIVITY-PHONE-01
Content-Type: application/json
```

#### Request body

```json
{
  "activity_id": "ACT-ORG-B-20260816-002",
  "participant": {
    "full_name": "陳美玲",
    "phone": "+853-6234-5678",
    "age": 80,
    "library_reader_card": true
  },
  "preferred_call_window": {
    "date": "2026-08-04",
    "from": "10:00",
    "to": "11:30",
    "timezone": "Asia/Macau"
  },
  "confirmation": {
    "confirmation_id": "CONF-20260803-0060",
    "confirmed_at": "2026-08-03T09:10:20+08:00",
    "displayed_summary_hash": "sha256:mock-phone-summary-001"
  }
}
```

#### Response `202 Accepted`

```json
{
  "request_id": "REQ-20260803-0060",
  "data": {
    "assistance": {
      "assistance_id": "PRA-20260803-0001",
      "activity_id": "ACT-ORG-B-20260816-002",
      "activity_title": "公共圖書館 e 學堂：手機應用入門",
      "organization_id": "ORG-B",
      "method": "phone",
      "status": "ready_for_call",
      "organization_phone": "+853-6200-2001",
      "phone_hours": "星期一至日 10:00-19:00，公眾假期除外",
      "required_information": ["姓名", "聯絡電話", "年齡", "是否持有圖書館讀者證"],
      "call_script": [
        "你好，我想報名 2026年8月16日的「公共圖書館 e 學堂：手機應用入門」。",
        "參加者姓名是陳美玲，80歲，聯絡電話是 +853-6234-5678。",
        "請問現在還有名額嗎？報名成功後需要帶甚麼資料？"
      ],
      "next_action": "由 Agent 或長者在服務時間致電機構，並把結果更新到此協助任務。",
      "created_at": "2026-08-03T09:10:25+08:00",
      "expires_at": "2026-08-13T19:00:00+08:00"
    },
    "task": {
      "task_id": "TASK-20260803-0060",
      "workflow_type": "elderly_activity_phone_registration_v1",
      "status": "waiting_for_phone_call",
      "current_step": "call_organization"
    }
  }
}
```

Demo UI 應顯示「已準備電話報名資料」或「等待致電」，不可顯示「已成功報名」。只有機構實際確認名額後，才可由後續人工或 mock callback 更新結果。

#### 可能錯誤

| HTTP | `error.code` | 說明 |
| --- | --- | --- |
| `409` | `FORM_REGISTRATION_AVAILABLE` | 該活動可用線上表格，應改用 `POST /registrations`。 |
| `409` | `ACTIVITY_FULL` | 建立協助時活動已沒有名額。 |
| `409` | `DUPLICATE_PHONE_ASSISTANCE` | 同一 mock 使用者已有未完成的電話協助任務。 |
| `422` | `MISSING_CALL_INFORMATION` | 缺少活動要求的通話資料。 |
| `422` | `CONFIRMATION_REQUIRED` | 沒有 Ponte Workflow 的明確確認記錄。 |

---

## 11. 查詢電話報名協助任務

### `GET /phone-registration-assists/{assistanceId}`

#### Request

```http
GET /mock/elderly-activities/v1/phone-registration-assists/PRA-20260803-0001
X-Mock-User-Id: USR-DEMO-001
X-Request-Id: REQ-20260803-0070
```

#### Response `200 OK`

```json
{
  "request_id": "REQ-20260803-0070",
  "data": {
    "assistance_id": "PRA-20260803-0001",
    "activity_id": "ACT-ORG-B-20260816-002",
    "activity_title": "公共圖書館 e 學堂：手機應用入門",
    "organization_id": "ORG-B",
    "method": "phone",
    "status": "waiting_for_phone_call",
    "organization_phone": "+853-6200-2001",
    "created_at": "2026-08-03T09:10:25+08:00",
    "updated_at": "2026-08-03T09:10:25+08:00",
    "next_action": "等待 Agent 或長者致電機構",
    "events": [
      {
        "event_type": "phone_assistance_created",
        "timestamp": "2026-08-03T09:10:25+08:00"
      }
    ]
  }
}
```

`status=completed` 只表示電話協助流程已經由人工／Demo 操作更新完成；若要表示機構已確認名額，應額外提供 `organization_confirmation`，包括機構確認時間和對方提供的參考編號。

---

## 12. Agent 對接及 Demo 流程

### 12.1 示例：按需求搜索

長者說：

> 「我想下星期在氹仔參加一些唱歌或者手機活動，最好可以打電話報名，唔想填太多表格。」

Agent 可將需求轉換為：

```http
GET /mock/elderly-activities/v1/activities?date_from=2026-08-10&date_to=2026-08-16&district=氹仔&category=arts,learning&registration_method=phone&available_only=true&sort=start_at_asc
```

Agent 回讀結果時應說明：

1. 活動由哪一間機構提供。
2. 活動名稱、日期、時間和地點。
3. 活動是否適合長者及還有多少名額。
4. 費用及需要攜帶的物品。
5. 是填表還是打電話報名。
6. 若是電話報名，提供電話和服務時間；若是填表，先取得長者選擇後再讀取表格欄位。

### 12.2 填表分支

```text
1. GET /activities?...
2. 長者選擇 ACT-ORG-A-20260808-001
3. GET /activities/{activityId}
4. GET /activities/{activityId}/registration-form
5. Agent 逐項收集姓名、電話、年齡及選填支援資料
6. UI 顯示報名摘要、資料使用同意及提交後果
7. 長者確認
8. POST /registrations + Idempotency-Key
9. GET /registrations/{registrationId}
10. 產生 Action Receipt
```

### 12.3 電話分支

```text
1. GET /activities?...
2. 長者選擇 ACT-ORG-B-20260816-002
3. GET /activities/{activityId}
4. Agent 說明電話、服務時間、所需資料及仍未完成正式報名
5. Agent 收集電話報名所需資料
6. UI 顯示通話摘要並取得長者確認
7. POST /phone-registration-assists + Idempotency-Key
8. UI 顯示電話號碼、通話提示及 waiting_for_phone_call
9. 由人工／Demo 操作致電後，再更新或讀取協助任務結果
10. 產生 Action Receipt，清楚區分「已建立協助」和「機構已確認」
```

### 12.4 MCP Tool 對應

| MCP tool | 對應 API | 建議風險 | 說明 |
| --- | --- | --- | --- |
| `one_account.search_elderly_activities` | `GET /activities` | `R0` | 跨機構活動搜索。 |
| `one_account.get_elderly_activity` | `GET /activities/{activityId}` | `R0` | 活動詳情及報名方式。 |
| `one_account.get_activity_registration_form` | `GET /activities/{activityId}/registration-form` | `R1` | 讀取表格 schema。 |
| `one_account.submit_activity_registration` | `POST /registrations` | `R2` | 必須有長者確認。 |
| `one_account.start_phone_registration_assistance` | `POST /phone-registration-assists` | `R2` | 必須有長者確認；不代表已撥號。 |
| `one_account.get_activity_registration_status` | `GET /registrations/{registrationId}` 或 `GET /phone-registration-assists/{assistanceId}` | `R1` | 追蹤報名或協助任務。 |

---

## 13. Mock fixture 規則

1. `ORG-A` 和 `ORG-B` 必須同時存在，且可以用 `organization_id` 分開查詢。
2. 每個機構至少有三項 `published` 活動。
3. 每個機構至少有一項 `registration.method=form` 和一項 `registration.method=phone`。
4. 預設 mock clock 為 `2026-08-03T09:00:00+08:00` 時，A、B 的示例活動都必須尚未開始、仍在報名期內及有剩餘名額。
5. 活動資料不得使用真實長者個人資料；報名 response 中的電話必須遮罩展示。
6. POST endpoint 必須支援 idempotency；重試不能新增第二份報名或電話協助任務。
7. 可另外準備 `ACTIVITY_FULL`、`ACTIVITY_CLOSED`、`PHONE_REGISTRATION_REQUIRED`、`MISSING_REQUIRED_FIELD` fixture，供 Demo 展示錯誤及分支處理。

---

## 14. 非功能及安全限制

- API 只保存 Demo 必要的 mock 個人資料，並在查詢回應中遮罩電話。
- 活動列表和詳情不需要真實身份驗證；正式報名及電話協助必須有 `X-Mock-User-Id`。
- 報名資料只能由相同 mock user 查詢。
- API 不提供醫療、法律或投資建議；健康生活活動只作行政活動資料展示。
- Agent 不可以因為成功建立電話協助任務，就宣稱機構已確認名額。
- Agent 不可以在沒有長者明確確認時提交表格或建立電話協助任務。

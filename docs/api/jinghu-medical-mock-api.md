# 鏡湖通醫療 Mock API 文檔

> 版本：`v1`  
> 最後更新：2026-08-03  
> 狀態：Ponte Demo Mock Contract

本 API 是 Ponte Demo 使用的鏡湖通醫療服務模擬介面，提供門診掛號、檢查／治療預約及「我的預約」查詢。它只模擬行政流程，不連接鏡湖醫院正式系統，不讀取真實病歷，也不提供診斷或臨床建議。

## 1. 設計來源與範圍

鏡湖通首頁目前將「網上掛號」、「檢查／治療預約」及「我的」列為獨立功能入口；公開門診資料亦顯示網上預約通常需要選擇科室、醫生、日期和時段。本 Mock API 依照這種使用流程提供合理的測試資料，但資料、ID、名額及規則均為虛構。

主要流程：

```text
查詢科室
  → 查詢門診掛號時段
  → 建立門診掛號

查詢檢查／治療服務
  → 查詢預約時段
  → 建立檢查／治療預約

查詢我的預約
  → 查看單筆預約及任務狀態
```

不在本版範圍：取消預約、改期、支付、報告查閱、電子健康紀錄、真實身份驗證及臨床資料交換。

## 2. API 共用約定

### 2.1 Base URL

```text
http://localhost:8080/mock/medical/v1
```

部署至 Ponte Backend 時，可將 Base URL 替換為實際 mock service 位址；所有相對路徑均以此 Base URL 為基準。

### 2.2 Headers

| Header | 必填 | 說明 |
| --- | --- | --- |
| `Authorization` | 是 | Mock token，例如 `Bearer mock-user-token`。不執行真實 OAuth。 |
| `X-Patient-Id` | 查詢個人資料時必填 | 當前就診人，例如 `P-10001`。代表已完成 mock 身份驗證的病人。 |
| `Content-Type` | POST 必填 | 固定為 `application/json`。 |
| `Idempotency-Key` | POST 必填 | 避免重試時重複掛號或預約，例如 `task-3821-step-book-1`。 |
| `Accept-Language` | 否 | `zh-TW` 或 `en-US`；預設為 `zh-TW`。 |

### 2.3 日期及時間

- 日期格式：`YYYY-MM-DD`。
- 時間格式：ISO 8601，例如 `2026-08-12T10:30:00+08:00`。
- 所有時間均以澳門時區 `Asia/Macau`（`+08:00`）解讀。
- Mock 預設只開放未來 14 日內的網上掛號／預約時段。

### 2.4 Mock 業務規則

1. `X-Patient-Id` 只接受 seed data 中存在的病人，例如 `P-10001`。
2. 一個 `Slot` 只能成功佔用一次；同一時段被其他請求佔用時回傳 `409 SLOT_NOT_AVAILABLE`。
3. 同一病人在同一科室、同一日期不可建立兩筆相同類型的有效掛號。
4. POST 操作必須帶 `Idempotency-Key`；相同 key 重試會返回第一次成功結果，不會新增第二筆資源。
5. 掛號和預約成功後，API 返回 `Appointment` 及對應的 `Task` 摘要，供 Workflow Orchestrator 產生事件及 Action Receipt。
6. `visit_reason` 和 `notes` 只接受非臨床的行政備註；不得填寫診斷、處方或醫療判斷。

### 2.5 Demo 持久化

Ponte mock backend 預設使用 repository root 下、與 `mock_backends/` 同級的 `database/` 作為資料根目錄。Medical 建立操作會以 JSON Lines 格式寫入：

```text
database/
├── id_sequences.txt
└── medical/
    ├── appointments.txt
    ├── tasks.txt
    └── idempotency.txt
```

`appointments.txt` 和 `tasks.txt` 保存建立後的 mock state，`idempotency.txt` 保存 POST 重試所需的第一次 response，`id_sequences.txt` 保存跨 backend 重啟仍不重複的 readable mock ID。這些文件只包含本地 demo 資料，不是真實病歷或醫院資料；可用 backend 的 `--data-dir` 或完整 stack runner 的 `--data-dir` 覆寫資料根目錄。

## 3. 資源模型

### 3.1 Department

```json
{
  "resourceType": "Department",
  "id": "DEPT-CARDIO",
  "name": "心臟科",
  "name_en": "Cardiology",
  "location_id": "LOC-MAIN-OPD",
  "location_name": "第一門診",
  "booking_modes": ["outpatient_registration", "follow_up"],
  "active": true
}
```

### 3.2 Doctor

```json
{
  "resourceType": "Practitioner",
  "id": "DOC-001",
  "name": "陳醫生",
  "name_en": "Dr. Chan",
  "department_id": "DEPT-CARDIO",
  "specialty": "心臟科",
  "active": true
}
```

### 3.3 Slot

```json
{
  "resourceType": "Slot",
  "id": "SLOT-REG-20260812-CARDIO-1030",
  "status": "free",
  "slot_type": "outpatient_registration",
  "department_id": "DEPT-CARDIO",
  "doctor_id": "DOC-001",
  "location_id": "LOC-MAIN-OPD",
  "start": "2026-08-12T10:30:00+08:00",
  "end": "2026-08-12T10:45:00+08:00",
  "capacity": 10,
  "remaining": 6
}
```

`slot_type` 可為：

| 值 | 用途 |
| --- | --- |
| `outpatient_registration` | 門診網上掛號 |
| `examination` | 檢查預約，例如超聲波或 CT |
| `treatment` | 治療預約，例如物理治療 |

### 3.4 Appointment

門診掛號和檢查／治療預約共用以下 FHIR-inspired 資源：

```json
{
  "resourceType": "Appointment",
  "id": "APT-20260803-0001",
  "status": "booked",
  "appointment_type": "outpatient_registration",
  "registration_number": "A08642",
  "patient": {
    "id": "P-10001",
    "display": "陳先生"
  },
  "department": {
    "id": "DEPT-CARDIO",
    "display": "心臟科"
  },
  "doctor": {
    "id": "DOC-001",
    "display": "陳醫生"
  },
  "service": null,
  "location": {
    "id": "LOC-MAIN-OPD",
    "display": "第一門診"
  },
  "start": "2026-08-12T10:30:00+08:00",
  "end": "2026-08-12T10:45:00+08:00",
  "booking_source": "ponte_mock",
  "created_at": "2026-08-03T14:01:25+08:00",
  "instructions": ["請於預約時間前到科室接待處報到"],
  "task_id": "TASK-20260803-0001"
}
```

`status` 可為：`pending`、`booked`、`confirmed`、`checked_in`、`completed`、`cancelled`、`no_show`。

### 3.5 Task

```json
{
  "resourceType": "Task",
  "id": "TASK-20260803-0001",
  "business_type": "medical_registration",
  "status": "completed",
  "appointment_id": "APT-20260803-0001",
  "workflow_type": "medical_registration_v1",
  "current_step": "complete",
  "created_at": "2026-08-03T14:01:25+08:00",
  "updated_at": "2026-08-03T14:01:26+08:00"
}
```

`Task.status` 可為：`created`、`submitted`、`waiting_for_external_result`、`completed`、`failed`、`cancelled`。

## 4. Endpoint 總覽

| 方法 | 路徑 | 用途 |
| --- | --- | --- |
| `GET` | `/departments` | 查詢可網上辦理的科室 |
| `GET` | `/departments/{departmentId}/doctors` | 查詢科室醫生 |
| `GET` | `/registration-slots` | 查詢門診掛號時段 |
| `POST` | `/registrations` | 建立門診掛號 |
| `GET` | `/appointment-services` | 查詢檢查／治療服務 |
| `GET` | `/appointment-slots` | 查詢檢查／治療可預約時段 |
| `POST` | `/appointments` | 建立檢查／治療預約 |
| `GET` | `/appointments` | 查詢我的預約 |
| `GET` | `/appointments/{appointmentId}` | 查詢單筆預約 |
| `GET` | `/tasks/{taskId}` | 查詢提交任務狀態 |

## 5. 科室及醫生

### 5.1 查詢科室

```http
GET /mock/medical/v1/departments?location_id=LOC-MAIN-OPD&keyword=%E5%BF%83
Authorization: Bearer mock-user-token
```

Query parameters：

| 欄位 | 必填 | 類型 | 說明 |
| --- | --- | --- | --- |
| `location_id` | 否 | string | `LOC-MAIN-OPD` 或 `LOC-TAIPA-MC`。 |
| `keyword` | 否 | string | 按中文或英文科室名稱搜尋。 |
| `active_only` | 否 | boolean | 預設 `true`。 |

`200 OK`：

```json
{
  "data": [
    {
      "resourceType": "Department",
      "id": "DEPT-CARDIO",
      "name": "心臟科",
      "name_en": "Cardiology",
      "location_id": "LOC-MAIN-OPD",
      "location_name": "第一門診",
      "booking_modes": ["outpatient_registration", "follow_up"],
      "active": true
    },
    {
      "resourceType": "Department",
      "id": "DEPT-ENT",
      "name": "耳鼻喉科",
      "name_en": "Otorhinolaryngology",
      "location_id": "LOC-MAIN-OPD",
      "location_name": "第一門診",
      "booking_modes": ["outpatient_registration"],
      "active": true
    }
  ],
  "meta": {"total": 2}
}
```

### 5.2 查詢科室醫生

```http
GET /mock/medical/v1/departments/DEPT-CARDIO/doctors
Authorization: Bearer mock-user-token
```

`200 OK`：

```json
{
  "data": [
    {
      "resourceType": "Practitioner",
      "id": "DOC-001",
      "name": "陳醫生",
      "name_en": "Dr. Chan",
      "department_id": "DEPT-CARDIO",
      "specialty": "心臟科",
      "active": true
    },
    {
      "resourceType": "Practitioner",
      "id": "DOC-002",
      "name": "李醫生",
      "name_en": "Dr. Lee",
      "department_id": "DEPT-CARDIO",
      "specialty": "心臟科",
      "active": true
    }
  ],
  "meta": {"total": 2}
}
```

## 6. 門診掛號

### 6.1 查詢掛號時段

```http
GET /mock/medical/v1/registration-slots?department_id=DEPT-CARDIO&date=2026-08-12&doctor_id=DOC-001
Authorization: Bearer mock-user-token
X-Patient-Id: P-10001
```

Query parameters：

| 欄位 | 必填 | 類型 | 說明 |
| --- | --- | --- | --- |
| `department_id` | 是 | string | 目標科室。 |
| `date` | 是 | date | 就診日期；必須在未來 14 日內。 |
| `doctor_id` | 否 | string | 指定醫生；不填表示不指定醫生。 |
| `session` | 否 | enum | `morning` 或 `afternoon`。 |
| `location_id` | 否 | string | 指定門診地點。 |

`200 OK`：

```json
{
  "data": [
    {
      "resourceType": "Slot",
      "id": "SLOT-REG-20260812-CARDIO-1030",
      "status": "free",
      "slot_type": "outpatient_registration",
      "department_id": "DEPT-CARDIO",
      "doctor_id": "DOC-001",
      "location_id": "LOC-MAIN-OPD",
      "start": "2026-08-12T10:30:00+08:00",
      "end": "2026-08-12T10:45:00+08:00",
      "capacity": 10,
      "remaining": 6
    },
    {
      "resourceType": "Slot",
      "id": "SLOT-REG-20260812-CARDIO-1100",
      "status": "free",
      "slot_type": "outpatient_registration",
      "department_id": "DEPT-CARDIO",
      "doctor_id": "DOC-001",
      "location_id": "LOC-MAIN-OPD",
      "start": "2026-08-12T11:00:00+08:00",
      "end": "2026-08-12T11:15:00+08:00",
      "capacity": 10,
      "remaining": 3
    }
  ],
  "meta": {
    "total": 2,
    "timezone": "Asia/Macau",
    "booking_window_days": 14
  }
}
```

### 6.2 建立門診掛號

```http
POST /mock/medical/v1/registrations
Authorization: Bearer mock-user-token
X-Patient-Id: P-10001
Idempotency-Key: task-3821-step-registration-1
Content-Type: application/json
```

Request body：

| 欄位 | 必填 | 類型 | 說明 |
| --- | --- | --- | --- |
| `patient_id` | 是 | string | 必須與 `X-Patient-Id` 相同。 |
| `department_id` | 是 | string | 由科室查詢取得。 |
| `doctor_id` | 否 | string | 必須屬於指定科室。 |
| `slot_id` | 是 | string | 由掛號時段查詢取得。 |
| `visit_reason` | 否 | string | 非臨床行政備註，例如「覆診」。 |
| `consent` | 是 | boolean | 必須為 `true`，表示同意建立 mock 掛號。 |

Request：

```json
{
  "patient_id": "P-10001",
  "department_id": "DEPT-CARDIO",
  "doctor_id": "DOC-001",
  "slot_id": "SLOT-REG-20260812-CARDIO-1030",
  "visit_reason": "覆診",
  "consent": true
}
```

`201 Created`：

```json
{
  "data": {
    "resourceType": "Appointment",
    "id": "APT-20260803-0001",
    "status": "booked",
    "appointment_type": "outpatient_registration",
    "registration_number": "A08642",
    "patient": {"id": "P-10001", "display": "陳先生"},
    "department": {"id": "DEPT-CARDIO", "display": "心臟科"},
    "doctor": {"id": "DOC-001", "display": "陳醫生"},
    "location": {"id": "LOC-MAIN-OPD", "display": "第一門診"},
    "start": "2026-08-12T10:30:00+08:00",
    "end": "2026-08-12T10:45:00+08:00",
    "booking_source": "ponte_mock",
    "created_at": "2026-08-03T14:01:25+08:00",
    "instructions": ["請於預約時間前到科室接待處報到"],
    "task_id": "TASK-20260803-0001"
  },
  "task": {
    "resourceType": "Task",
    "id": "TASK-20260803-0001",
    "business_type": "medical_registration",
    "status": "completed",
    "workflow_type": "medical_registration_v1",
    "current_step": "complete"
  },
  "receipt": {
    "reference": "MED-REG-88219",
    "issued_at": "2026-08-03T14:01:26+08:00"
  }
}
```

## 7. 檢查／治療預約

### 7.1 查詢檢查／治療服務

```http
GET /mock/medical/v1/appointment-services?department_id=DEPT-IMAGING&type=examination
Authorization: Bearer mock-user-token
```

Query parameters：

| 欄位 | 必填 | 類型 | 說明 |
| --- | --- | --- | --- |
| `department_id` | 否 | string | 指定服務科室。 |
| `type` | 否 | enum | `examination` 或 `treatment`。 |
| `keyword` | 否 | string | 搜尋服務名稱。 |
| `active_only` | 否 | boolean | 預設 `true`。 |

`200 OK`：

```json
{
  "data": [
    {
      "resourceType": "HealthcareService",
      "id": "SERVICE-US-001",
      "name": "腹部超聲波檢查",
      "name_en": "Abdominal Ultrasound",
      "type": "examination",
      "department_id": "DEPT-IMAGING",
      "location_id": "LOC-IMAGING-CENTER",
      "duration_minutes": 30,
      "requires_referral": true,
      "active": true
    },
    {
      "resourceType": "HealthcareService",
      "id": "SERVICE-PT-001",
      "name": "物理治療",
      "name_en": "Physical Therapy",
      "type": "treatment",
      "department_id": "DEPT-REHAB",
      "location_id": "LOC-REHAB-01",
      "duration_minutes": 45,
      "requires_referral": true,
      "active": true
    }
  ],
  "meta": {"total": 2}
}
```

### 7.2 查詢檢查／治療時段

```http
GET /mock/medical/v1/appointment-slots?service_id=SERVICE-US-001&date_from=2026-08-10&date_to=2026-08-14
Authorization: Bearer mock-user-token
X-Patient-Id: P-10001
```

Query parameters：

| 欄位 | 必填 | 類型 | 說明 |
| --- | --- | --- | --- |
| `service_id` | 是 | string | 由服務查詢取得。 |
| `date_from` | 是 | date | 搜尋開始日期。 |
| `date_to` | 是 | date | 搜尋結束日期；不可超過 `date_from` 後 14 日。 |
| `doctor_id` | 否 | string | 指定操作人員／醫生。 |
| `location_id` | 否 | string | 指定服務地點。 |

`200 OK`：

```json
{
  "data": [
    {
      "resourceType": "Slot",
      "id": "SLOT-US-20260812-1400",
      "status": "free",
      "slot_type": "examination",
      "service_id": "SERVICE-US-001",
      "department_id": "DEPT-IMAGING",
      "location_id": "LOC-IMAGING-CENTER",
      "start": "2026-08-12T14:00:00+08:00",
      "end": "2026-08-12T14:30:00+08:00",
      "capacity": 1,
      "remaining": 1
    }
  ],
  "meta": {
    "total": 1,
    "timezone": "Asia/Macau",
    "booking_window_days": 14
  }
}
```

### 7.3 建立檢查／治療預約

```http
POST /mock/medical/v1/appointments
Authorization: Bearer mock-user-token
X-Patient-Id: P-10001
Idempotency-Key: task-3821-step-examination-1
Content-Type: application/json
```

Request body：

| 欄位 | 必填 | 類型 | 說明 |
| --- | --- | --- | --- |
| `patient_id` | 是 | string | 必須與 `X-Patient-Id` 相同。 |
| `service_id` | 是 | string | 檢查或治療服務。 |
| `slot_id` | 是 | string | 由可用時段查詢取得。 |
| `referring_appointment_id` | 否 | string | 關聯的門診掛號 ID。 |
| `administrative_note` | 否 | string | 非臨床行政備註。 |
| `consent` | 是 | boolean | 必須為 `true`。 |

Request：

```json
{
  "patient_id": "P-10001",
  "service_id": "SERVICE-US-001",
  "slot_id": "SLOT-US-20260812-1400",
  "referring_appointment_id": "APT-20260803-0001",
  "administrative_note": "請按指示提前報到",
  "consent": true
}
```

`201 Created`：

```json
{
  "data": {
    "resourceType": "Appointment",
    "id": "APT-20260803-0002",
    "status": "confirmed",
    "appointment_type": "examination",
    "patient": {"id": "P-10001", "display": "陳先生"},
    "service": {
      "id": "SERVICE-US-001",
      "display": "腹部超聲波檢查"
    },
    "department": {"id": "DEPT-IMAGING", "display": "影像科"},
    "location": {"id": "LOC-IMAGING-CENTER", "display": "影像中心"},
    "start": "2026-08-12T14:00:00+08:00",
    "end": "2026-08-12T14:30:00+08:00",
    "booking_source": "ponte_mock",
    "created_at": "2026-08-03T14:05:25+08:00",
    "instructions": [
      "請攜帶有效身份證明",
      "請於預約時間前 15 分鐘到影像中心報到"
    ],
    "task_id": "TASK-20260803-0002"
  },
  "task": {
    "resourceType": "Task",
    "id": "TASK-20260803-0002",
    "business_type": "medical_appointment",
    "status": "completed",
    "workflow_type": "medical_appointment_v1",
    "current_step": "complete"
  },
  "receipt": {
    "reference": "MED-APT-88220",
    "issued_at": "2026-08-03T14:05:26+08:00"
  }
}
```

## 8. 查詢我的預約

### 8.1 查詢預約清單

```http
GET /mock/medical/v1/appointments?status=booked,confirmed&date_from=2026-08-01&date_to=2026-08-31&page=1&page_size=20
Authorization: Bearer mock-user-token
X-Patient-Id: P-10001
```

Query parameters：

| 欄位 | 必填 | 類型 | 說明 |
| --- | --- | --- | --- |
| `status` | 否 | string | 逗號分隔：`pending`、`booked`、`confirmed`、`completed`、`cancelled`。 |
| `appointment_type` | 否 | enum | `outpatient_registration`、`examination` 或 `treatment`。 |
| `date_from` | 否 | date | 按開始時間過濾。 |
| `date_to` | 否 | date | 按開始時間過濾。 |
| `page` | 否 | integer | 預設 `1`。 |
| `page_size` | 否 | integer | 預設 `20`，最大 `100`。 |

`X-Patient-Id` 是此 endpoint 的資料邊界；API 不接受用 query parameter 指定其他病人的 ID。

`200 OK`：

```json
{
  "data": [
    {
      "resourceType": "Appointment",
      "id": "APT-20260803-0001",
      "status": "booked",
      "appointment_type": "outpatient_registration",
      "registration_number": "A08642",
      "department": {"id": "DEPT-CARDIO", "display": "心臟科"},
      "doctor": {"id": "DOC-001", "display": "陳醫生"},
      "location": {"id": "LOC-MAIN-OPD", "display": "第一門診"},
      "start": "2026-08-12T10:30:00+08:00",
      "end": "2026-08-12T10:45:00+08:00",
      "task_id": "TASK-20260803-0001"
    },
    {
      "resourceType": "Appointment",
      "id": "APT-20260803-0002",
      "status": "confirmed",
      "appointment_type": "examination",
      "service": {"id": "SERVICE-US-001", "display": "腹部超聲波檢查"},
      "department": {"id": "DEPT-IMAGING", "display": "影像科"},
      "location": {"id": "LOC-IMAGING-CENTER", "display": "影像中心"},
      "start": "2026-08-12T14:00:00+08:00",
      "end": "2026-08-12T14:30:00+08:00",
      "task_id": "TASK-20260803-0002"
    }
  ],
  "meta": {
    "page": 1,
    "page_size": 20,
    "total": 2,
    "has_next": false
  }
}
```

### 8.2 查詢單筆預約

```http
GET /mock/medical/v1/appointments/APT-20260803-0001
Authorization: Bearer mock-user-token
X-Patient-Id: P-10001
```

`200 OK`：回傳完整 `Appointment`，格式與建立掛號／預約的 `data` 相同。若預約不屬於 `X-Patient-Id`，Mock API 一律回傳 `404 APPOINTMENT_NOT_FOUND`，避免暴露其他病人的資料。

## 9. 查詢任務狀態

### 9.1 查詢提交任務

```http
GET /mock/medical/v1/tasks/TASK-20260803-0001
Authorization: Bearer mock-user-token
X-Patient-Id: P-10001
```

`200 OK`：

```json
{
  "data": {
    "resourceType": "Task",
    "id": "TASK-20260803-0001",
    "business_type": "medical_registration",
    "status": "completed",
    "appointment_id": "APT-20260803-0001",
    "workflow_type": "medical_registration_v1",
    "current_step": "complete",
    "events": [
      {
        "step_id": "validate_patient",
        "event_type": "validation_succeeded",
        "timestamp": "2026-08-03T14:01:25+08:00"
      },
      {
        "step_id": "submit_registration",
        "event_type": "registration_created",
        "timestamp": "2026-08-03T14:01:26+08:00"
      }
    ],
    "updated_at": "2026-08-03T14:01:26+08:00"
  }
}
```

## 10. 錯誤格式與狀態碼

所有錯誤使用同一格式：

```json
{
  "error": {
    "code": "SLOT_NOT_AVAILABLE",
    "message": "所選時段已被其他掛號佔用。",
    "details": {
      "slot_id": "SLOT-REG-20260812-CARDIO-1030"
    },
    "request_id": "REQ-20260803-00017",
    "timestamp": "2026-08-03T14:07:02+08:00"
  }
}
```

| HTTP | `error.code` | 說明 |
| --- | --- | --- |
| `400` | `INVALID_REQUEST` | JSON 格式錯誤或欄位格式不正確。 |
| `400` | `MISSING_REQUIRED_FIELD` | 缺少必填欄位。 |
| `401` | `AUTH_REQUIRED` | 缺少或無效的 mock token。 |
| `403` | `PATIENT_CONTEXT_MISMATCH` | body 的 `patient_id` 與 `X-Patient-Id` 不一致。 |
| `404` | `DEPARTMENT_NOT_FOUND` | 科室不存在或已停用。 |
| `404` | `SLOT_NOT_FOUND` | 時段不存在、已過期或不屬於指定服務。 |
| `404` | `APPOINTMENT_NOT_FOUND` | 預約不存在或不屬於當前病人。 |
| `404` | `PATIENT_NOT_FOUND` | mock 病人不存在。 |
| `409` | `SLOT_NOT_AVAILABLE` | 時段已無剩餘名額。 |
| `409` | `DUPLICATE_BOOKING` | 同一病人已有衝突的有效掛號／預約。 |
| `409` | `IDEMPOTENCY_KEY_REUSED` | 同一 key 被用於不同 request body。 |
| `422` | `BOOKING_WINDOW_EXCEEDED` | 日期超出 mock 預設 14 日預約窗口。 |
| `422` | `CONSENT_REQUIRED` | `consent` 不是 `true`。 |
| `422` | `REFERRAL_REQUIRED` | 該檢查／治療需要關聯門診或轉介資料。 |
| `500` | `MOCK_SERVICE_ERROR` | 模擬外部醫療系統暫時錯誤，可由 Workflow 重試。 |

## 11. Ponte Workflow／MCP 對接

此 API 可由 Medical MCP Server 封裝成以下工具：

| MCP tool | 對應 API | 建議風險 |
| --- | --- | --- |
| `medical.list_departments` | `GET /departments` | `R0` |
| `medical.list_department_doctors` | `GET /departments/{departmentId}/doctors` | `R0` |
| `medical.search_registration_slots` | `GET /registration-slots` | `R1` |
| `medical.create_registration` | `POST /registrations` | `R2` |
| `medical.list_appointment_services` | `GET /appointment-services` | `R0` |
| `medical.search_appointment_slots` | `GET /appointment-slots` | `R1` |
| `medical.create_appointment` | `POST /appointments` | `R2` |
| `medical.get_my_appointments` | `GET /appointments` | `R1` |
| `medical.get_appointment` | `GET /appointments/{appointmentId}` | `R1` |
| `medical.get_task_status` | `GET /tasks/{taskId}` | `R1` |

`R2` 操作必須由 Ponte Workflow 在提交前顯示科室／服務、日期、時間、地點和病人，並取得明確確認；LLM 不可直接跳過確認節點或直接寫入 Mock Service。

## 12. 端到端示例

### 12.1 「幫我掛心臟科下星期三上午」

```text
1. GET /departments?keyword=心臟
2. GET /registration-slots?department_id=DEPT-CARDIO&date=2026-08-12&session=morning
3. Ponte 顯示科室、醫生、日期、時間和地點
4. 使用者確認
5. POST /registrations + Idempotency-Key
6. GET /tasks/{taskId}，確認 Task.status=completed
7. 產生 Action Receipt，記錄 registration_number 和 appointment_id
```

### 12.2 「幫我預約腹部超聲波」

```text
1. GET /appointment-services?type=examination&keyword=超聲
2. GET /appointment-slots?service_id=SERVICE-US-001&date_from=2026-08-10&date_to=2026-08-14
3. Ponte 顯示檢查項目、日期、時間、地點和報到提示
4. 使用者確認
5. POST /appointments + Idempotency-Key
6. GET /appointments/{appointmentId}，確認 Appointment.status=confirmed
7. 產生 Action Receipt，記錄 appointment_id 和 task_id
```

### 12.3 「睇下我有咩預約」

```text
1. 使用已驗證的 X-Patient-Id 呼叫 GET /appointments
2. 按 appointment_type 顯示門診掛號、檢查及治療預約
3. 使用者選擇某筆預約後呼叫 GET /appointments/{appointmentId}
4. 如需追蹤提交過程，再呼叫 GET /tasks/{taskId}
```

## 13. 參考資料

- [鏡湖通首頁](https://app.kwh.org.mo/)
- [鏡湖醫院門診服務說明](https://www.kwh.org.mo/kwh/article/361)
- 專案架構文件：`docs/PonteArch.md`

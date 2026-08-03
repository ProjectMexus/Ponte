# 鏡湖通醫療 Mock API 文檔 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立一份符合 Ponte Arch 的鏡湖通醫療 Mock API Markdown 文檔，覆蓋科室掛號、檢查／治療預約及我的預約查詢。

**Architecture:** 以 `/mock/medical` 為 API 根路徑，將門診掛號與檢查／治療預約建模為共同的 FHIR-inspired `Appointment` 資源，並用 `Slot`、`Department`、`Doctor`、`Task` 支援查詢和 Durable Workflow 展示。

**Tech Stack:** Markdown、JSON request/response 範例、HTTP REST 介面；不新增 runtime dependency，不連接真實醫療服務。

## Global Constraints

- 所有接口均為 mock，不得暗示為鏡湖醫院正式 API。
- 醫療功能只處理行政掛號及預約，不涉及診斷、臨床建議或真實病歷。
- 資料格式採用 FHIR-inspired JSON，與 `PonteArch.md` 的 `Appointment`、`Slot`、`Task` 方向一致。
- 建立操作必須說明 `X-Patient-Id` 及 `Idempotency-Key`。
- 時間統一使用 `Asia/Macau`（`+08:00`）。

---

### Task 1: 寫入設計與 API 合約文檔

**Files:**
- Create: `docs/superpowers/specs/2026-08-03-jinghu-medical-mock-api-design.md`
- Create: `docs/api/jinghu-medical-mock-api.md`

**Interfaces:**
- Produces: REST endpoint contract for department lookup, outpatient registration, examination/treatment appointment booking, appointment listing, appointment detail, and task status.

- [ ] **Step 1: 建立文檔目錄及設計說明**

  建立設計說明，列出目的、範圍、非目標、參考依據及驗收條件；明確標示 mock、FHIR-inspired 和私隱限制。

- [ ] **Step 2: 寫入共用 API 約定**

  在 API 文檔中定義 Base URL、`X-Patient-Id`、`Authorization`、`Idempotency-Key`、時間格式、分頁格式、錯誤格式及資源狀態。

- [ ] **Step 3: 寫入三條核心流程**

  以完整 request/response JSON 描述：

  1. `GET /departments` → `GET /registration-slots` → `POST /registrations`。
  2. `GET /appointment-services` → `GET /appointment-slots` → `POST /appointments`。
  3. `GET /appointments` → `GET /appointments/{appointmentId}`。

- [ ] **Step 4: 補充 Arch 對接資訊**

  將 endpoint 對應至 `medical.list_departments`、`medical.search_registration_slots`、`medical.create_registration`、`medical.search_appointment_slots`、`medical.create_appointment`、`medical.get_my_appointments` 及 `medical.get_task_status`。

### Task 2: 文檔一致性驗證

**Files:**
- Verify: `docs/api/jinghu-medical-mock-api.md`
- Verify: `docs/superpowers/specs/2026-08-03-jinghu-medical-mock-api-design.md`

**Interfaces:**
- Consumes: API paths, field names, enum values and JSON examples written in Task 1.
- Produces: verified documentation with no unresolved placeholders or contradictory field definitions.

- [ ] **Step 1: 搜尋未完成標記**

  Run: `rg -n "TBD|TODO|待補|待定|PLACEHOLDER" docs/api/jinghu-medical-mock-api.md docs/superpowers/specs/2026-08-03-jinghu-medical-mock-api-design.md`

  Expected: no matches.

- [ ] **Step 2: 檢查必需章節及 endpoint**

  Run: `rg -n "GET /mock/medical/departments|GET /mock/medical/registration-slots|POST /mock/medical/registrations|GET /mock/medical/appointment-services|GET /mock/medical/appointment-slots|POST /mock/medical/appointments|GET /mock/medical/appointments|Appointment|Slot|Task|錯誤" docs/api/jinghu-medical-mock-api.md`

  Expected: every required path and resource concept is present.

- [ ] **Step 3: 檢查 Git diff**

  Run: `git diff --check -- docs/api docs/superpowers`

  Expected: no whitespace errors. If the workspace has no Git repository, use `rg --files docs/api docs/superpowers` and inspect the files directly instead.

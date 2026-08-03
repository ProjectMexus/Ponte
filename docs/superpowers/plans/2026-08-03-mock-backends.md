# Ponte Mock Backends Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 建立三個獨立、可替換且可持久化的 Python 標準庫 mock domain backend，完整對應目前的一戶通、長者文娛活動、醫療 API 文件，並依 PonteArch 補上社會福利轉介 API。

**Architecture:** 使用單一可啟動的 HTTP process，但將 one_account、medical、social_welfare 放在獨立資料夾，每個 domain 由 service interface、fixture/catalog、HTTP adapter 和 repository wiring 組成。共用 core 只處理 clock、錯誤、JSON envelope、idempotency、ID 和 JSON Lines txt repository；domain service 不依賴 HTTP 或具體文字檔，之後可由 MCP adapter、SQL repository 或真實 API client 替換。

**Tech Stack:** Python 3.11+ 標準庫、http.server、unittest、JSON Lines 格式的 .txt 文件；不新增第三方依賴。

## Global Constraints

- 所有 backend 都是 Ponte Demo / Mock，不連接真實政府、醫療或社福系統。
- 不實作真實身份驗證、OAuth、病歷、診斷、付款或真實電話撥出。
- 保留 docs/api 中已定義的 path、header、主要 request/response 欄位和狀態碼。
- 社會福利 endpoint 沒有獨立 docs/api，必須明確標示為 PonteArch-derived demo contract。
- 所有寫入操作必須支援 Idempotency-Key；同一 context、endpoint、key 同 body 重放第一次結果，不同 body 返回 409 IDEMPOTENCY_KEY_REUSED。
- 文字持久化文件放在可配置的 data/mock 目錄，測試不得寫入正式 data/mock。
- X-Mock-User-Id 和 X-Patient-Id 是資料邊界，不得讓查詢洩露其他使用者或病人資源。
- 時間使用 Asia/Macau（UTC+08:00）；測試注入固定 Clock。
- backend service 必須能在不啟動 HTTP server 的情況下直接被測試和日後 MCP adapter 調用。
- 每個 task 完成後執行該 task 的測試，並建立有意義的 git commit；若 git 再次被環境鎖定，保留變更並記錄原因。

---

### Task 1: 建立共用 core interfaces、錯誤與 txt 持久化

**Files:**
- Create: mock_backends/__init__.py
- Create: mock_backends/core/__init__.py
- Create: mock_backends/core/contracts.py
- Create: mock_backends/core/errors.py
- Create: mock_backends/core/clock.py
- Create: mock_backends/core/ids.py
- Create: mock_backends/core/persistence.py
- Create: mock_backends/core/idempotency.py
- Create: tests/core/test_persistence.py
- Create: tests/core/test_idempotency.py
- Create: tests/core/test_core_helpers.py

**Interfaces:**
- Produces Clock.now() -> datetime、FixedClock 和 AsiaMacauClock。
- Produces RecordRepository，包含 list()、get(record_id)、insert(record)、replace(record_id, record) 和 find(predicate)。
- Produces MemoryRepository 供 service tests 使用，以及 JsonLinesTextRepository 供 .txt 持久化使用。
- Produces IdempotencyStore.lookup(scope, key) 和 IdempotencyStore.remember(scope, key, request_hash, response)。
- Produces DomainError(status, code, message, details, retryable) 和 error_payload(request_id, error, clock)。
- Produces IdGenerator.next(prefix) -> str，以及測試可注入的 deterministic implementation。

- [x] Step 1: 寫 repository 與 helper failing tests

建立 tests，驗證 temporary records.txt 初始為空、insert 寫入一行 JSON object、新 repository instance 可以讀回、replace 只更新原 ID 不重複，以及空白／錯誤行會拋出清晰的 ValueError。另測試 FixedClock 返回注入的 UTC+08:00 datetime，DomainError 能序列化 code 和 retryable。

~~~python
def test_json_lines_repository_survives_reopen(self):
    repo = JsonLinesTextRepository(self.path, id_field="id")
    repo.insert({"id": "REC-1", "status": "new"})
    reopened = JsonLinesTextRepository(self.path, id_field="id")
    self.assertEqual(reopened.get("REC-1")["status"], "new")
~~~

- [x] Step 2: 執行 focused tests 確認失敗

Run: python -m unittest tests.core.test_persistence tests.core.test_core_helpers -v

Expected: FAIL，因為 core modules 和 repository classes 尚未存在。

- [x] Step 3: 實作 core contracts 與最小實作

使用 typing.Protocol 定義 interfaces。JsonLinesTextRepository 必須建立 parent directories、每行寫一個 compact JSON object、先寫 sibling temporary file 再用 os.replace 原子替換，並以 threading.RLock 保護 read-modify-write。MemoryRepository 需要在 input/output copy records，避免測試直接修改內部狀態。FixedClock 必須保存 timezone-aware datetime 並拒絕 naive datetime。

- [x] Step 4: 加入 idempotency persistence 與 tests

測試 miss、同 scope hit、scope isolation、相同 key 搭配不同 request hash 時拋出 DomainError(409, IDEMPOTENCY_KEY_REUSED, ...)，以及 repository reopen 後仍能 replay。保存第一次 response 的 status 和 JSON body，使 HTTP retry 可以重放完整 response。

- [x] Step 5: 執行 core tests 並 commit

Run: python -m unittest discover -s tests/core -v

Expected: PASS。

Commit: git add mock_backends tests/core && git commit -m "feat: add mock backend core interfaces and text persistence"

---

### Task 2: 實作獨立 One Account backend

**Files:**
- Create: mock_backends/one_account/__init__.py
- Create: mock_backends/one_account/fixtures.py
- Create: mock_backends/one_account/contracts.py
- Create: mock_backends/one_account/service.py
- Create: mock_backends/one_account/backend.py
- Create: tests/one_account/test_one_account_backend.py

**Interfaces:**
- OneAccountService.submit_pension_application(user_id, headers, body) -> BackendResponse。
- OneAccountService.get_cash_sharing_plan(user_id, query) -> BackendResponse。
- OneAccountService.create_queue_ticket(user_id, queue_type, body, headers) -> BackendResponse。
- OneAccountService.list_queue_tickets(user_id, query) -> BackendResponse。
- OneAccountBackend.handle(request: BackendRequest) -> BackendResponse。
- Service constructor 接收 Clock、IdGenerator、application/ticket repositories 和 IdempotencyStore。

- [x] Step 1: 寫 failing tests

覆蓋：
1. pension 缺少 X-Mock-User-Id 返回 401 AUTH_REQUIRED。
2. pension 缺少 identity_document 或 bank_account_proof 返回 422 MISSING_DOCUMENT。
3. data_processing=false 返回 422 CONSENT_REQUIRED。
4. 合法 pension body 返回 201、application ID 和 receipt，且只建立一筆 record。
5. 相同 user、endpoint、idempotency key 和 body 重試返回相同 201 response；改 body 返回 409。
6. cash-sharing year=2026 返回 mock eligibility/payout；不支援年份返回 404 PLAN_NOT_FOUND。
7. 兩類 queue ticket 都接受文件指定 contract，缺 confirmation 拒絕；list 只返回目前 user 的 tickets。

- [x] Step 2: 執行 focused tests 確認失敗

Run: python -m unittest tests.one_account.test_one_account_backend -v

Expected: FAIL，因為 One Account modules 尚未存在。

- [x] Step 3: 實作 fixtures 與 service rules

只在 One Account 檔案放 service-center catalog、cash-sharing plan fixture 和 application validation。產生 PEN-*、Q-GSC-*、Q-IDB-* IDs、mock receipt references、queue number、wait estimate 和 Macau timestamps。相同 user、center、service type、requested date 的有效 ticket 返回 409 ACTIVE_TICKET_EXISTS。兩個 queue POST 都要求 confirmation 和 Idempotency-Key。

- [x] Step 4: 實作 One Account path adapter

精確支援：
- /mock/one-account/pension/applications
- /mock/one-account/cash-sharing-plan
- /mock/one-account/queue-tickets/government-service-center
- /mock/one-account/queue-tickets/identification-services-bureau
- /mock/one-account/my/queue-tickets

使用 urllib.parse 解析 query，unsupported method 返回 405，所有 response 都有傳入或生成的 request ID。path dispatch 放在 backend.py，service.py 不直接解析 HTTP。

- [x] Step 5: 執行 tests 並 commit

Run: python -m unittest tests.one_account.test_one_account_backend -v

Expected: PASS。

Commit: git add mock_backends/one_account tests/one_account && git commit -m "feat: add one account mock backend"

---

### Task 3: 在 Social Welfare domain 加入長者文娛活動

**Files:**
- Create: mock_backends/social_welfare/activity_fixtures.py
- Create: mock_backends/social_welfare/activity_service.py
- Create: mock_backends/social_welfare/activity_backend.py
- Modify: mock_backends/server.py
- Create: tests/social_welfare/test_activity_backend.py

**Interfaces:**
- ElderlyActivitiesService.search(query) -> BackendResponse。
- ElderlyActivitiesService.get_activity(activity_id, request_id) -> BackendResponse。
- ElderlyActivitiesService.get_registration_form(activity_id, request_id) -> BackendResponse。
- ElderlyActivitiesService.create_registration(user_id, body, headers, request_id, path) -> BackendResponse。
- ElderlyActivitiesService.get_registration(user_id, registration_id, request_id) -> BackendResponse。
- ElderlyActivitiesService.create_phone_assistance(user_id, body, headers, request_id, path) -> BackendResponse。
- ElderlyActivitiesService.get_phone_assistance(user_id, assistance_id, request_id) -> BackendResponse。

- [x] Step 1: 寫 failing activity tests

使用包含 ORG-A、ORG-B、至少一項 form 和一項 phone 的 fixtures。測試：
1. 預設 search 只返回 published、尚未開始、open 且 remaining > 0 的活動。
2. organization_id、category、registration_method、district、date、keyword、pagination 和 sort=start_at_asc filters 有效。
3. detail/form unknown ID 返回 404；phone-only 活動呼叫 form 返回 409 REGISTRATION_METHOD_NOT_SUPPORTED。
4. 合法 form registration 要求 user header、method match、required fields、consents.data_processing=true 和 confirmation；返回 201 並只能由同 user 讀取。
5. 合法 phone assistance 返回 202、waiting_for_phone_call 或 ready_for_call，並明確保留「尚未完成官方報名」語意。
6. idempotency replay 正常，full activity 返回 409 ACTIVITY_FULL。

- [x] Step 2: 執行 focused tests 確認失敗

Run: python -m unittest tests.one_account.test_activity_backend -v

Expected: FAIL，因為 activity methods 和 fixtures 尚未存在。

- [x] Step 3: 實作 activity catalog 和 search

定義完整 mock records：organization、schedule、venue、audience、fee、availability、registration method、contact、registration window、tags、accessibility、instructions。fixture clock 配合 2026-08-03T09:00:00+08:00。keyword 搜 title、summary、tags、organization name；解析 comma-separated type/category/accessibility；回傳 pagination metadata。

- [x] Step 4: 實作 form registration 與 phone-assistance branches

registration 和 phone assistance 使用不同 repository。activity read response 按 API 文檔遮罩 phone。POST 要求 X-Mock-User-Id 和 Idempotency-Key。phone assistance 只允許 mock assistance statuses，response 必須清楚表示尚未完成 official registration。

- [x] Step 5: 執行 tests 並 commit

Run: python -m unittest tests.one_account.test_one_account_backend tests.one_account.test_activity_backend -v

Expected: PASS。

Commit: git add mock_backends/social_welfare tests/social_welfare mock_backends/server.py && git commit -m "feat: add elderly activity backend under social welfare"

---

### Task 4: 實作獨立 Medical backend

**Files:**
- Create: mock_backends/medical/__init__.py
- Create: mock_backends/medical/fixtures.py
- Create: mock_backends/medical/contracts.py
- Create: mock_backends/medical/service.py
- Create: mock_backends/medical/backend.py
- Create: tests/medical/test_medical_backend.py

**Interfaces:**
- MedicalService.list_departments(query) -> BackendResponse。
- MedicalService.list_department_doctors(patient_id, department_id) -> BackendResponse。
- MedicalService.search_registration_slots(patient_id, query) -> BackendResponse。
- MedicalService.create_registration(patient_id, body, headers) -> BackendResponse。
- MedicalService.list_appointment_services(query) -> BackendResponse。
- MedicalService.search_appointment_slots(patient_id, query) -> BackendResponse。
- MedicalService.create_appointment(patient_id, body, headers) -> BackendResponse。
- MedicalService.list_appointments(patient_id, query) -> BackendResponse。
- MedicalService.get_appointment(patient_id, appointment_id) -> BackendResponse。
- MedicalService.get_task(patient_id, task_id) -> BackendResponse。
- MedicalBackend.handle(request: BackendRequest) -> BackendResponse。

- [x] Step 1: 寫 failing medical tests

覆蓋：
1. patient-scoped routes 缺少或無效 X-Patient-Id 返回 401 AUTH_REQUIRED。
2. department/doctor lookup 返回 fixtures 並支援 keyword。
3. registration slots 驗證 department/date，只返回 matching free slots。
4. registration body patient mismatch 返回 403 PATIENT_CONTEXT_MISMATCH；consent=false 返回 422 CONSENT_REQUIRED；unknown slot 返回 404；已消耗 slot 返回 409 SLOT_NOT_AVAILABLE。
5. 合法 registration 返回 201 FHIR-inspired Appointment、completed Task、receipt，並遞減 slot remaining。
6. appointment service/slot 支援 examination/treatment filter。
7. examination booking 驗證 service/slot relation 和 referral requirement；list/detail/task 不可洩露其他 patient。
8. 相同 idempotency request replay；不同 body 同 key 返回 409。

- [x] Step 2: 執行 focused tests 確認失敗

Run: python -m unittest tests.medical.test_medical_backend -v

Expected: FAIL，因為 Medical modules 尚未存在。

- [x] Step 3: 實作 FHIR-inspired fixture catalog 和 validation

定義 Department、Practitioner、Slot、HealthcareService、Appointment、Task fixture dictionaries，欄位名和 resourceType 對齊 docs/api/jinghu-medical-mock-api.md。相對注入 Clock 實作 14 日 booking window。分開 registration/appointment slots，驗證 patient context、slot capacity，產生 MED-REG-* 或 MED-APT-* receipt references。

- [x] Step 4: 實作 Medical path adapter

精確支援：
- /mock/medical/v1/departments
- /mock/medical/v1/departments/{departmentId}/doctors
- /mock/medical/v1/registration-slots
- /mock/medical/v1/registrations
- /mock/medical/v1/appointment-services
- /mock/medical/v1/appointment-slots
- /mock/medical/v1/appointments
- /mock/medical/v1/appointments/{appointmentId}
- /mock/medical/v1/tasks/{taskId}

使用文件指定 Authorization: Bearer mock-user-token convention；patient isolation 依 X-Patient-Id。屬於另一 patient 的 resource 統一返回 404。

- [x] Step 5: 執行 tests 並 commit

Run: python -m unittest tests.medical.test_medical_backend -v

Expected: PASS。

Commit: git add mock_backends/medical tests/medical && git commit -m "feat: add medical mock backend"

---

### Task 5: 實作獨立 Social Welfare backend

**Files:**
- Create: mock_backends/social_welfare/__init__.py
- Create: mock_backends/social_welfare/README.md
- Create: mock_backends/social_welfare/fixtures.py
- Create: mock_backends/social_welfare/contracts.py
- Create: mock_backends/social_welfare/service.py
- Create: mock_backends/social_welfare/backend.py
- Create: tests/social_welfare/test_social_welfare_backend.py

**Interfaces:**
- SocialWelfareService.search_services(query) -> BackendResponse。
- SocialWelfareService.create_referral(user_id, body, headers) -> BackendResponse。
- SocialWelfareService.get_referral(user_id, referral_id) -> BackendResponse。
- SocialWelfareService.assign_referral(user_id, referral_id, body, headers) -> BackendResponse。
- SocialWelfareBackend.handle(request: BackendRequest) -> BackendResponse。

- [x] Step 1: 寫 failing Arch-derived contract tests

使用 escorted transport、accompaniment、community care、phone welfare support fixtures。測試：
1. service search 支援 keyword、category、district、accessibility、active status。
2. 缺少 X-Mock-User-Id、consents.data_sharing=false 或缺 confirmation 時，建立 referral 以 shared error shape rejected。
3. 合法 referral 返回 201，包含 referral_id、PENDING、case summary、preferred contact 和 mock receipt。
4. same-user detail 可讀；another user 返回 404。
5. assign pending referral 返回 200、ASSIGNED 和 mock case worker；unknown/already assigned 返回 deterministic 404/409。
6. idempotency replay 不建立 duplicate referral。

- [x] Step 2: 執行 focused tests 確認失敗

Run: python -m unittest tests.social_welfare.test_social_welfare_backend -v

Expected: FAIL，因為 Social Welfare modules 尚未存在。

- [x] Step 3: 實作 Arch-derived contract

在 social_welfare/README.md 明確說明 routes 來源是 PonteArch.md section 8.3，不是 official API，且只實作 demo 最小範圍。固定 shapes：
- search response data.services：service_id、name、category、summary、districts、accessibility、contact、active。
- referral request：service_id、subject、need_summary、preferred_contact、consents.data_sharing、confirmation。
- referral response：referral、receipt；referral 含 referral_id、status、created_at、assigned_worker、next_action、service。
- assign request：case_worker_id 或空 body；response 更新 status=ASSIGNED 並附 case_worker。

- [x] Step 4: 實作 path adapter 和 persistence wiring

支援 /mock/social-welfare/services、/mock/social-welfare/referrals、/mock/social-welfare/referrals/{referralId}、/mock/social-welfare/referrals/{referralId}/assign。service catalog 只讀；只在 social welfare data directory 持久化 referrals 和 idempotency records。

- [x] Step 5: 執行 tests 並 commit

Run: python -m unittest tests.social_welfare.test_social_welfare_backend -v

Expected: PASS。

Commit: git add mock_backends/social_welfare tests/social_welfare && git commit -m "feat: add social welfare mock backend"

---

### Task 6: 加入 shared router、HTTP server 和 end-to-end smoke tests

**Files:**
- Create: mock_backends/core/http.py
- Create: mock_backends/router.py
- Create: mock_backends/server.py
- Create: tests/test_http_smoke.py
- Create: tests/test_persistence_restart.py

**Interfaces:**
- BackendRequest(method, path, headers, query, body, request_id)。
- BackendResponse(status, body, headers)。
- MockRouter.mount(prefix, backend) 和 MockRouter.dispatch(request)。
- create_application(data_dir, clock=None) -> MockRouter。
- run_server(host, port, data_dir)。
- CLI: python -m mock_backends.server --host 127.0.0.1 --port 8080 --data-dir data/mock。

- [x] Step 1: 寫 failing HTTP smoke tests

啟動 ephemeral ThreadingHTTPServer 並以 http.client.HTTPConnection 呼叫。驗證：
1. GET /mock/one-account/cash-sharing-plan 返回 200 和 request_id。
2. GET /mock/medical/v1/departments 返回 200。
3. GET /mock/social-welfare/services 返回 200。
4. 合法 One Account queue POST 返回 201 和 JSON content type。
5. 合法 Medical registration POST 返回 201，follow-up GET 能看到 Appointment。
6. unknown route 返回 404；malformed JSON 返回 400；unexpected service exception 返回 500 且不洩露 traceback。
7. 一個 application instance 建立的 referral，在同 data directory 建立第二個 application instance 後仍可讀到。

- [x] Step 2: 執行 smoke tests 確認失敗

Run: python -m unittest tests.test_http_smoke tests.test_persistence_restart -v

Expected: FAIL，因為 HTTP adapter、router、server entrypoint 尚未存在。

- [x] Step 3: 實作 request/response normalization 和 router

core/http.py 解析 JSON body、normalize case-insensitive headers、缺 request ID 時生成、輸出 application/json; charset=utf-8、serialize 所有 success/error payload。router.py 按 longest mounted prefix 選 backend；delegate 前只移除 mount prefix；沒有 mount 時返回 shared 404。

- [x] Step 4: 實作 server factory 和 CLI

將 one_account、medical、social_welfare 各自 repositories wiring 到 data/mock/<domain>。使用 ThreadingHTTPServer 和小型 request handler 委派 MockRouter；business logic 不放 handler。tests 能 clean shutdown；CLI 用 argparse 支援 host、port、data-dir。

- [x] Step 5: 執行 full suite 並 commit

Run: python -m unittest discover -s tests -v

Expected: PASS。

Commit: git add mock_backends tests && git commit -m "feat: expose mock backends through HTTP server"

---

### Task 7: 加入 demo documentation 和 final verification

**Files:**
- Create: README.md
- Create: data/mock/.gitkeep
- Modify: mock_backends/server.py，只在需要補充 CLI help 或 startup output 時修改。

**Interfaces:**
- README 產出 startup command、endpoint examples、persistence layout、test command、domain boundaries 和 MCP adapter seam。

- [x] Step 1: 寫 README acceptance checks

執行：
- rg -n "python -m mock_backends.server|/mock/one-account|/mock/medical/v1|/mock/social-welfare|Idempotency-Key|X-Mock-User-Id|X-Patient-Id" README.md mock_backends docs
- rg -n "TBD|TODO|PLACEHOLDER|待補|待定" README.md mock_backends tests

第一個 command 必須找到所有 startup/path/header 概念；第二個 command 不應有 output。

- [x] Step 2: 寫 demo workflow 文件

用簡潔內容說明 Python version、startup、三個 domain 的 curl examples、--data-dir、test command、.txt storage warning，以及未來 MCP server 應該調用 domain service interfaces 而不是直接讀文件或 HTTP internals。連結三份 API 文檔和 social welfare README。

- [x] Step 3: 驗證格式與行為

Run:
- python -m unittest discover -s tests -v
- python -m compileall -q mock_backends tests
- git diff --check
- git status --short

Expected: tests PASS、compileall exit 0、diff check 無 output，且只變更預期 backend/test/docs files。

- [x] Step 4: Commit final documentation

Commit: git add README.md data/mock/.gitkeep && git commit -m "docs: add mock backend demo guide"

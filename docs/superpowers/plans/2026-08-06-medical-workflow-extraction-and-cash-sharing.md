# Medical Workflow Extraction and Cash Sharing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task, and delegate bounded independent checks or disjoint edits to sub-agents where useful. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the working medical Demo into a concrete `MedicalWorkflow`, reduce `InteractionCore` to task/workflow orchestration, cut medical legacy routing, and add a concrete read-only `CashSharingWorkflow` without inventing receipt semantics.

**Architecture:** Keep five practical layers: frontend, `InteractionCore`, concrete workflows, the existing `ExecutionPipeline` execution boundary, and backend APIs. `InteractionCore` loads and saves the active task and selects a concrete workflow; each workflow owns task transitions, tool calls, verification, recovery, safe facts, and any truthful receipt. Keep the `ExecutionPipeline` name during the Demo and do not add registries, a workflow framework, generic state machines, or abstract verifier/receipt systems.

**Tech Stack:** Python 3.12, standard-library HTTP server and dataclasses, existing MCP registry/client, existing mock backends, browser JavaScript, pytest/unittest.

## Global Constraints

- Every refactor must directly enable the medical or cash-sharing Demo.
- Do not add `WorkflowRegistry`, `VerifierRegistry`, `ReceiptRegistry`, a workflow DSL, a generic artifact framework, or a workflow base-class hierarchy.
- `InteractionCore` may know task-type and intent-to-workflow mappings, but it must not contain medical/cash steps, tool names, backend-shape validation, recovery mappings, or receipt construction.
- Workflows decide `task.status`, `task.current_step`, facts, confirmation, recovery, and receipt. Core only loads the task, calls the workflow, and saves the returned task.
- Keep `ExecutionPipeline` and `dispatch()` names. Moving tool execution out of Core is required; renaming the execution class is explicitly deferred until after the Demo.
- The Demo keeps one active task per session and does not add task versions, confirmation expiry, durable execution attempts, or production idempotency infrastructure.
- Cash sharing is a read-only query. It completes with verified safe facts and `receipt: null`.
- For cash sharing, `task.status="completed"` means only that the plan lookup completed. It must never imply that an application, eligibility adjudication, payment, or payout completed; backend statuses such as `OPEN`, `ELIGIBLE`, and `SCHEDULED` must be preserved without upgrading their meaning.
- Preserve this explicit TODO in code and documentation: `Cash-sharing receipt semantics remain undefined until the backend issues a business reference and timestamp. Do not derive a receipt from transport or middleware IDs.`
- Apply the same rule to incomplete backend workflows: do not invent completion or receipt semantics. Return the backend-supported intermediate/read-only state and leave an explicit contract TODO.
- Server-issued action events include `action_id` and `task_id`; the frontend returns them unchanged.
- Do not stage or modify the user's existing `.env.example`, image, zip, or log changes.
- Scope clarification: remove medical and cash ownership from the legacy controller/routes. Keep the smallest legacy controller surface needed by elderly-activity and MCP diagnostic flows until the activity migration; do not claim the entire legacy controller can be deleted in this slice.

---

### Task 1: Extract the complete medical behavior into `MedicalWorkflow`

**Files:**
- Create: `middleware/medical_workflow.py`
- Create: `middleware/tests/test_medical_workflow.py`
- Modify: `middleware/interaction_contracts.py`
- Modify: `middleware/interaction_core.py`
- Modify: `middleware/tests/test_interaction_core.py`

**Interfaces:**
- Produces `MedicalWorkflow.start(envelope, intent) -> tuple[dict[str, Any], CanonicalInteractionResult]`.
- Produces `MedicalWorkflow.handle(task, envelope) -> tuple[dict[str, Any], CanonicalInteractionResult]`.
- `MedicalWorkflow` receives the existing `ExecutionPipeline`, trusted patient/user context, and no Core/session persistence object.
- Keeps medical verification and receipt construction as medical implementation details in `medical_workflow.py`; no verifier or receipt registry is created.

- [x] **Step 1: Add characterization tests around the current medical behavior.** Move the existing fake-pipeline medical cases from `test_interaction_core.py` into `test_medical_workflow.py`. Cover service listing, slot selection, complete confirmation targets, verified completion, invalid-backend recovery, retry, caller-controlled referral rejection, cancellation, and repeated approval.

```python
def test_medical_workflow_approval_returns_completed_task_and_receipt():
    workflow = medical_workflow(FakePipeline())
    task, pending = reach_confirmation(workflow)
    approve = next(
        action["event"]
        for action in pending.allowed_actions
        if action["event"].get("decision") == "approve"
    )

    task, completed = workflow.handle(task, envelope("INT-4", approve))

    assert task["status"] == "completed"
    assert completed.receipt["receipt_id"] == "MED-APT-1"
    assert task["receipt"] == completed.receipt
```

- [x] **Step 2: Run the new characterization tests before extraction.**

Run:

```powershell
& 'C:\Users\steph\AppData\Local\Programs\Python\Python312\python.exe' -m pytest middleware/tests/test_medical_workflow.py -q
```

Expected: FAIL because `middleware.medical_workflow` does not exist.

- [x] **Step 3: Replace `MedicalTask` with a task record that is not medically named.** Rename only the data record, not the workflow architecture. Keep the existing fields and require explicit workflow values.

```python
@dataclass
class InteractionTask:
    task_id: str
    type: str
    status: str
    current_step: str
    facts: dict[str, Any] = field(default_factory=dict)
    pending_confirmation: dict[str, Any] | None = None
    recovery: dict[str, Any] | None = None
    receipt: dict[str, Any] | None = None
```

Medical task creation must remain concrete:

```python
task = InteractionTask(
    task_id=_identifier("TASK"),
    type="medical_appointment",
    status="awaiting_input",
    current_step="select_service",
).to_dict()
```

- [x] **Step 4: Move the complete medical behavior without redesigning it.** Move these responsibilities from `InteractionCore` into `MedicalWorkflow`: medical start/query/booking paths, service/slot actions, confirmation transitions, retry storage, trusted context creation, idempotency derivation, interaction logging, exception-to-result mapping, tool-call construction and dispatch through the injected `ExecutionPipeline`, medical recovery mapping, safe service/slot extraction, result verification, receipt construction, and medical result/action assembly. Keep `_execute` private to `MedicalWorkflow`; do not add another executor abstraction.

```python
class MedicalWorkflow:
    task_type = "medical_appointment"

    def start(self, envelope: EventEnvelope, intent: IntentDecision):
        task = self._new_task()
        if intent.is_medical_query:
            return self._load_appointments(task, envelope)
        return self._load_services(task, envelope)

    def handle(self, task: dict[str, Any], envelope: EventEnvelope):
        event_type = envelope.event["type"]
        if event_type == "service_selected":
            return self._service_selected(task, envelope)
        if event_type == "slot_selected":
            return self._slot_selected(task, envelope)
        if event_type == "confirmation_decision":
            return self._confirmation_decision(task, envelope)
        if event_type == "recovery_action":
            return self._recovery_action(task, envelope)
        if event_type == "cancel_task":
            return self._cancel(task, envelope)
        raise ValueError(f"unsupported medical event: {event_type}")
```

- [x] **Step 5: Keep the current medical verifier and receipt behavior local to the workflow.** Move `MedicalResultVerifier` and `ActionReceiptBuilder` out of the shared contracts module. They may remain small private classes or functions in `medical_workflow.py`; do not generalize them. Preserve the existing validation rules exactly: require a successful tool result, a mapping payload, appointment status `BOOKED`, backend task status `COMPLETED`, and a backend receipt containing non-empty `receipt_id` and `issued_at`. Return only the existing user-safe appointment fields plus those two receipt fields. `_build_receipt` must use the active task ID, preserve the backend `receipt_id` and `issued_at`, and exclude patient IDs, authorization context, raw tool payloads, and transport request IDs.

- [x] **Step 6: Add the dispatch-ownership test and run workflow, execution, and contract tests.** Verify that `MedicalWorkflow` dispatches through its injected fake pipeline and that `InteractionCore` is not involved in tool execution.

Run:

```powershell
& 'C:\Users\steph\AppData\Local\Programs\Python\Python312\python.exe' -m pytest middleware/tests/test_medical_workflow.py middleware/tests/test_interaction_contracts.py middleware/tests/test_execution.py -q
```

Expected: PASS.

- [x] **Step 7: Commit the complete medical extraction.**

```powershell
git add middleware/medical_workflow.py middleware/interaction_contracts.py middleware/tests/test_medical_workflow.py middleware/tests/test_interaction_contracts.py
git commit -m "refactor: extract complete medical workflow"
```

---

### Task 2: Reduce `InteractionCore` to orchestration and task persistence

**Files:**
- Modify: `middleware/interaction_core.py`
- Modify: `middleware/server.py`
- Modify: `middleware/interaction_voice.py`
- Modify: `middleware/tests/test_interaction_core.py`
- Modify: `middleware/tests/test_interaction_voice.py`

**Interfaces:**
- `InteractionCore.handle(envelope) -> CanonicalInteractionResult` remains the public API.
- Core receives concrete workflow instances; it does not define a workflow registry abstraction.
- Core explicitly maps a new intent or existing `task.type` to a workflow.

- [x] **Step 1: Replace medical behavior tests with Core ownership tests.** Use tiny fake workflows. Assert Core selects a workflow, passes a copy of the active task, saves the returned task, and does not decide domain steps.

```python
def test_core_saves_task_returned_by_selected_workflow():
    medical = FakeWorkflow(
        task_type="medical_appointment",
        returned_task={
            "task_id": "TASK-1",
            "type": "medical_appointment",
            "status": "awaiting_input",
            "current_step": "select_slot",
            "facts": {"service_id": "SERVICE-US-001"},
        },
    )
    core = core_with(medical=medical)

    result = core.handle(user_utterance("S-1", "我想預約醫療服務"))

    state = core.sessions.get_or_create("S-1")
    assert state.task["current_step"] == "select_slot"
    assert result.task == state.task
```

- [x] **Step 2: Run Core tests to verify they fail against the medical Core.**

Run:

```powershell
& 'C:\Users\steph\AppData\Local\Programs\Python\Python312\python.exe' -m pytest middleware/tests/test_interaction_core.py -q
```

Expected: FAIL because Core still owns medical transitions.

- [x] **Step 3: Implement explicit, minimal routing.** Do not introduce a base class or registry object.

```python
def handle(self, envelope: EventEnvelope) -> CanonicalInteractionResult:
    state = self.sessions.get_or_create(envelope.session_id)
    if envelope.event["type"] == "user_utterance":
        intent = self.intent_recognizer.recognize(envelope.event["content"])
        workflow = self._workflow_for_intent(intent)
        task, result = workflow.start(envelope, intent)
    else:
        if not isinstance(state.task, dict):
            raise ValueError("task does not exist")
        workflow = self._workflow_for_task(state.task)
        task, result = workflow.handle(deepcopy(state.task), envelope)
    state.active_task_id = task["task_id"]
    state.task = deepcopy(task)
    return result


def _workflow_for_intent(self, intent):
    if intent.is_medical:
        return self.medical_workflow
    if intent.is_cash_sharing and self.cash_workflow is not None:
        return self.cash_workflow
    raise ValueError("unsupported interaction intent")


def _workflow_for_task(self, task):
    if task.get("type") == "medical_appointment":
        return self.medical_workflow
    if task.get("type") == "cash_sharing_query" and self.cash_workflow is not None:
        return self.cash_workflow
    raise ValueError("unsupported task type")
```

- [x] **Step 4: Remove all medical implementation from Core.** `interaction_core.py` must no longer contain medical tool names, service/slot field extraction, medical recovery codes, confirmation transitions, retry-step cases, or receipt construction.

Run:

```powershell
rg -n "medical\.|service_selected|slot_selected|create_appointment|MedicalResultVerifier|ActionReceiptBuilder|referring_appointment_id" middleware/interaction_core.py
```

Expected: no matches except a task-type routing string if retained.

- [x] **Step 5: Construct `MedicalWorkflow` in `MiddlewareApplication`.** Pass the existing `ExecutionPipeline`, patient ID, authorization, and mock user ID into the workflow, then pass the workflow into Core. Voice remains an adapter to the same Core and needs no medical dependency.

- [x] **Step 6: Run Core, voice, HTTP, and medical workflow tests.**

Run:

```powershell
& 'C:\Users\steph\AppData\Local\Programs\Python\Python312\python.exe' -m pytest middleware/tests/test_interaction_core.py middleware/tests/test_medical_workflow.py middleware/tests/test_interaction_voice.py middleware/tests/test_interaction_http.py -q
```

Expected: PASS.

- [x] **Step 7: Keep the Core changes uncommitted until the medical end-to-end path is green.** This task and Task 3 share one checkpoint commit.

---

### Task 3: Prove the medical Demo end to end on the single Core path

**Files:**
- Modify: `middleware/tests/test_interaction_http.py`
- Modify: `tests/test_middleware_integration.py`
- Modify: `tests/test_full_stack_integration.py`
- Modify: `tests/test_http_smoke.py` only if it currently asserts middleware legacy medical fields
- Modify: `tests/test_frontend_interaction_contract.py`

**Interfaces:**
- Medical HTTP requests use only `POST /api/interactions` with an `EventEnvelope`.
- Audio uses only `POST /api/voice/turn`, which creates the same normalized event.
- Medical actions submit `workspace.actions[].event` unchanged to `/api/interactions`.

- [x] **Step 1: Add a test helper that drives canonical actions.** Reuse server-issued actions rather than reconstructing service, slot, or confirmation payloads.

```python
def post_interaction(opener, base_url, session_id, interaction_id, event):
    return post_json(opener, base_url + "/api/interactions", {
        "routing": {"session_id": session_id, "interaction_id": interaction_id},
        "event": event,
    })


def action_event(response, *, decision=None):
    actions = response["workspace"]["actions"]
    if decision is None:
        return actions[0]["event"]
    return next(item["event"] for item in actions if item["event"].get("decision") == decision)
```

- [x] **Step 2: Rewrite the medical middleware integration path.** Exercise utterance → service action → slot action → approve action → completed task. Assert canonical response fields, verified receipt, no patient ID, and no legacy fields.

```python
assert final["task"]["status"] == "completed"
assert final["workspace"]["view"] == "appointment_completed"
assert final["receipt"]["receipt_id"].startswith("MED-APT-")
for removed in ("assistant_message", "task_state", "current_step", "tool_events"):
    assert removed not in final
```

- [x] **Step 3: Rewrite medical recovery tests to use canonical recovery actions.** Cover backend timeout retry and duplicate booking. Submit the exact retry event returned in `workspace.actions`; assert `awaiting_input`, deterministic recovery, and no receipt.

- [x] **Step 4: Rewrite full-stack medical tests.** Replace all natural-language medical requests to `/api/interactions/message` and all medical `/api/interactions/action` calls. Keep cash/activity/diagnostic legacy tests unchanged until their respective migration task.

- [x] **Step 5: Verify frontend ownership.** Keep static assertions that browser utterances and action events use `sendInteraction`; add an assertion that medical code contains no `/api/interactions/message` or `/api/interactions/action` string.

- [x] **Step 6: Run the medical end-to-end group.**

Run:

```powershell
$env:PONTE_ENV_FILE='E:\Steph''s repos\Ponte\missing-test-env'
& 'C:\Users\steph\AppData\Local\Programs\Python\Python312\python.exe' -m pytest middleware/tests/test_interaction_http.py middleware/tests/test_interaction_voice.py tests/test_middleware_integration.py tests/test_full_stack_integration.py tests/test_frontend_interaction_contract.py -q
```

Expected: PASS.

- [x] **Step 7: Commit the slim Core and green canonical medical path together.**

```powershell
git add middleware/interaction_core.py middleware/server.py middleware/interaction_voice.py middleware/tests/test_interaction_core.py middleware/tests/test_interaction_voice.py middleware/tests/test_interaction_http.py middleware/tests/test_medical_workflow.py tests/test_middleware_integration.py tests/test_full_stack_integration.py tests/test_http_smoke.py tests/test_frontend_interaction_contract.py
git commit -m "refactor: slim core and prove medical interaction path"
```

---

### Task 4: Remove medical ownership from the legacy controller and endpoints

**Files:**
- Modify: `middleware/controller.py`
- Modify: `middleware/server.py`
- Modify: `middleware/tests/test_controller.py`
- Modify: `middleware/tests/test_server.py`
- Modify: `tests/test_middleware_integration.py`
- Modify: `tests/test_full_stack_integration.py`

**Interfaces:**
- Legacy `/api/interactions/message` remains temporarily for elderly activity and MCP diagnostics only at this point.
- Legacy `/api/interactions/action` remains only for diagnostic confirmation/cancellation needed by those tests.
- Medical text/actions on legacy routes return a deterministic client error and never call medical tools.
- Diagnostic parsing remains before ordinary intent rejection, so commands such as `mcp medical.list_departments` continue to work.
- Preserve `GET /api/mcp/tools` and the GET-only execution behavior of `POST /api/mcp/tools/call`, including rejection of mutation tools that bypass confirmation.

- [x] **Step 1: Add failing route-closure tests.** Post medical booking/query text to the legacy message route and medical actions to the legacy action route. Assert a `400` error with `INTERACTION_EVENT_REQUIRED` and zero medical tool calls. Introduce a dedicated legacy-route exception and map it in both route handlers; do not rely on the existing generic `ValueError` mappings.

```python
def test_legacy_message_route_rejects_medical_workflow():
    status, payload = request_json("POST", "/api/interactions/message", {
        "session_id": "S-LEGACY-MED",
        "message": "我想預約醫療服務",
        "source": "text",
    })
    assert status == 400
    assert payload["error"]["code"] == "INTERACTION_EVENT_REQUIRED"
```

- [x] **Step 2: Remove medical branches from `InteractionController.handle_message`.** Keep cash, elderly activity, and diagnostics for the moment. Parse diagnostic commands first; after that, a recognized ordinary medical intent raises the dedicated unsupported-contract error before any tool call.

- [x] **Step 3: Remove legacy medical action handlers and state.** Delete controller-owned service selection, slot search/selection, confirmation, appointment creation, medical retry interpretation, and medical response construction. Retain `_handle_elderly_activity`, `_handle_diagnostic_message`, `_confirm_diagnostic`, `_cancel_diagnostic`, `_diagnostic_response`, `_run_tool`, `_context`, `_result_data`, `_set_error`, and their `TaskManager`/session dependencies. Retain at least `confirm_tool` and diagnostic-only `cancel` in the legacy action allowlist; accept `cancel` only when `pending_diagnostic` exists.

- [x] **Step 4: Remove legacy medical controller tests.** Their behavioral coverage must already exist under `test_medical_workflow.py` and canonical HTTP/integration tests. Keep diagnostic, cash, and activity controller tests until the related ownership is migrated.

- [x] **Step 5: Prove medical has one route and one workflow owner.**

Run:

```powershell
rg -n "_handle_medical|_search_slots|_select_slot|medical\.create_appointment|medical\.search_appointment_slots" middleware/controller.py middleware/server.py
```

Expected: no matches in either file. Medical tool names may appear only in `medical_workflow.py`, MCP registry/backend code, and tests.

- [x] **Step 6: Run controller/server, canonical medical, activity, and diagnostic tests.** Include characterization coverage for activity search; diagnostic GET; diagnostic POST confirmation/cancellation; malformed diagnostic commands; low-level mutation rejection; and `mcp medical.*` / `mcp one_account.*` diagnostic commands, which must not be mistaken for ordinary medical/cash utterances.

Run:

```powershell
& 'C:\Users\steph\AppData\Local\Programs\Python\Python312\python.exe' -m pytest middleware/tests/test_controller.py middleware/tests/test_server.py middleware/tests/test_medical_workflow.py middleware/tests/test_interaction_http.py tests/test_middleware_integration.py tests/test_full_stack_integration.py -q
```

Expected: PASS.

- [x] **Step 7: Commit legacy medical removal.**

```powershell
git add middleware/controller.py middleware/server.py middleware/tests/test_controller.py middleware/tests/test_server.py tests/test_middleware_integration.py tests/test_full_stack_integration.py
git commit -m "refactor: remove legacy medical workflow path"
```

---

### Task 5: Add the concrete read-only `CashSharingWorkflow`

**Files:**
- Create: `middleware/cash_sharing_workflow.py`
- Create: `middleware/tests/test_cash_sharing_workflow.py`
- Modify: `middleware/interaction_core.py`
- Modify: `middleware/interaction_delivery.py`
- Modify: `middleware/server.py`
- Modify: `middleware/controller.py`
- Modify: `middleware/tests/test_interaction_core.py`
- Modify: `middleware/tests/test_interaction_delivery.py`
- Modify: `middleware/tests/test_interaction_http.py`
- Modify: `middleware/tests/test_controller.py`
- Modify: `middleware/tests/test_server.py`
- Modify: `tests/test_full_stack_integration.py`
- Modify: `tests/test_frontend_interaction_contract.py`

**Interfaces:**
- Produces `CashSharingWorkflow.start(envelope, intent) -> tuple[dict[str, Any], CanonicalInteractionResult]`.
- Produces `CashSharingWorkflow.handle(task, envelope) -> tuple[dict[str, Any], CanonicalInteractionResult]` for retry, human-help, and cancel recovery events only.
- Uses task type `cash_sharing_query`.
- Uses steps `load_cash_sharing_plan` and `complete`.
- Success returns `response_intent="cash_sharing_summary"`, verified facts, no confirmation, no mutation actions, and `receipt=None`. Its completed task describes completion of the read-only lookup only.
- Recovery returns `response_intent="cash_sharing_recovery"`, `status="awaiting_input"`, and server-issued retry/human-help/cancel actions.

- [x] **Step 1: Write cash workflow contract tests.** Cover verified success, malformed backend result, backend failure/retry, safe facts, no receipt, and no transport/user identifiers.

```python
def test_cash_query_completes_with_verified_facts_and_no_receipt():
    task, result = workflow.start(
        user_envelope("INT-CASH-1", "我想查現金分享計劃"),
        cash_sharing_intent(),
    )

    assert task["type"] == "cash_sharing_query"
    assert task["status"] == "completed"
    assert task["current_step"] == "complete"
    assert result.response_intent == "cash_sharing_summary"
    assert result.facts["plan"]["plan_id"] == "CSP-2026"
    assert result.receipt is None
```

- [x] **Step 2: Run the cash tests to verify they fail.**

Run:

```powershell
& 'C:\Users\steph\AppData\Local\Programs\Python\Python312\python.exe' -m pytest middleware/tests/test_cash_sharing_workflow.py -q
```

Expected: FAIL because `CashSharingWorkflow` does not exist.

- [x] **Step 3: Implement the concrete cash task and a Demo-sized verifier.** Do not add a shared verifier interface. Call `one_account.get_cash_sharing_plan` with input `{}`; do not add year parsing, year-selection actions, or history browsing in this slice. Require only `plan_id`, `plan_name`, `year`, top-level `status`, `eligibility.eligible`, `payout.amount`, and `payout.currency`. Extract these required safe facts and include optional display fields only when their types are usable:

```python
{
    "plan": {
        "plan_id": "CSP-2026",
        "plan_name": "現金分享計劃",
        "year": 2026,
        "status": "OPEN",
        "eligibility": {
            "eligible": True,
            "status": "ELIGIBLE",
            "reason": "符合本 Demo 測試用的基本資格資料。",
        },
        "payout": {
            "amount": 10000,
            "currency": "MOP",
            "payment_status": "SCHEDULED",
            "scheduled_date": "2026-09-30",
        },
        "last_updated_at": "2026-08-06T00:00:00+08:00",
    },
    "history": [],
}
```

Reject missing or empty required strings, non-integer amount/year, or non-boolean `eligibility.eligible`. Do not fail the whole query because an optional `scheduled_date`, `last_updated_at`, eligibility reason/status, payment status, or history value is missing or imperfectly formatted; omit an unusable optional field from safe facts instead. Do not hardcode the fixture's plan ID, display name, or timestamp as contract values. Never copy request IDs, raw context, or mock user IDs.

- [x] **Step 4: Implement truthful cash completion and recovery.** A successful GET completes only the plan lookup. Response copy must preserve backend plan, eligibility, and payout statuses and must not claim that registration, eligibility adjudication, payment, or payout completed. A backend/tool error or malformed result becomes `awaiting_input` with retry/human-help/cancel; no confirmation and no receipt are created.

Keep this exact code comment next to the `receipt=None` result:

```python
# TODO: Cash-sharing receipt semantics remain undefined until the backend
# issues a business reference and timestamp. Never derive a receipt from
# ToolExecutionResult.request_id or a middleware-generated identifier.
```

- [x] **Step 5: Wire CashSharingWorkflow into the explicit Core routing.** Construct the concrete workflow in `MiddlewareApplication`; route `intent.is_cash_sharing` and task type `cash_sharing_query`. Do not add a workflow registry abstraction.

- [x] **Step 6: Add cash response and workspace projections.** Add explicit handling to the existing composer/projector implementation:

```text
response_intent: cash_sharing_summary
workspace.view: cash_sharing_summary
workspace.fields: plan name, year, eligibility, amount/currency,
                  payment status, scheduled date, last updated
workspace.actions: []
workspace.artifact: null
receipt: null
```

For `cash_sharing_recovery`, render the structured recovery reason and supplied server actions. Do not route a generic completed task to `appointment_completed`.

- [x] **Step 7: Migrate cash HTTP/full-stack tests to `/api/interactions`.** Assert voice/browser utterances now reach cash through Core, the workspace uses `cash_sharing_summary`, facts are verified, and no medical fields or receipt appear.

- [x] **Step 8: Remove cash ownership from the legacy controller.** Delete `_handle_cash_sharing` and its legacy response tests. As an explicit API deprecation in the direct-migration strategy, ordinary legacy cash text returns `INTERACTION_EVENT_REQUIRED`, just like medical; do not normalize it through a compatibility adapter. Diagnostic commands that name `one_account` tools remain supported. Leave elderly activity and MCP diagnostics untouched.

- [x] **Step 9: Run cash, shared Core, delivery, frontend, and backend contract tests.**

Run:

```powershell
$env:PONTE_ENV_FILE='E:\Steph''s repos\Ponte\missing-test-env'
& 'C:\Users\steph\AppData\Local\Programs\Python\Python312\python.exe' -m pytest middleware/tests/test_cash_sharing_workflow.py middleware/tests/test_interaction_core.py middleware/tests/test_interaction_delivery.py middleware/tests/test_interaction_http.py middleware/tests/test_server.py tests/test_full_stack_integration.py tests/test_frontend_interaction_contract.py tests/one_account/test_one_account_backend.py MCP/tests/test_registry.py -q
```

Expected: PASS.

- [x] **Step 10: Commit the cash-sharing workflow.**

```powershell
git add middleware/cash_sharing_workflow.py middleware/interaction_core.py middleware/interaction_delivery.py middleware/server.py middleware/controller.py middleware/tests/test_cash_sharing_workflow.py middleware/tests/test_interaction_core.py middleware/tests/test_interaction_delivery.py middleware/tests/test_interaction_http.py middleware/tests/test_controller.py middleware/tests/test_server.py tests/test_full_stack_integration.py tests/test_frontend_interaction_contract.py
git commit -m "feat: add cash sharing workflow to interaction core"
```

---

### Task 6: Verify two workflows and update design documentation last

**Files:**
- Create: `middleware/tests/test_interaction_architecture.py`
- Modify: `docs/superpowers/specs/2026-08-06-voice-first-medical-interaction-core-design.md`
- Modify: `docs/superpowers/plans/2026-08-06-voice-first-medical-interaction-core.md`
- Modify: `README.md` only if it documents the old interaction endpoints
- Test: `middleware/tests`
- Test: `tests`
- Test: `MCP/tests`

**Interfaces:**
- The final architecture has one Core path for medical and cash.
- Medical/cash domain transitions and verification live only in their concrete workflow modules.
- Legacy controller ownership is limited to elderly activity and MCP diagnostics until the next migration.

- [x] **Step 1: Add architecture-boundary regression tests.** Make behavioral ownership the primary guard: Core works with fake workflows and has no execution dependency; workflows own dispatch; legacy medical/cash routes cannot invoke their tools; and separate medical/cash sessions do not leak state. Keep source inspection narrow and secondary so comments, logging, or documentation strings do not cause false failures.

```python
def test_core_has_no_execution_dependency():
    parameters = inspect.signature(InteractionCore.__init__).parameters
    assert "pipeline" not in parameters
    assert "executor" not in parameters


def test_legacy_medical_route_cannot_dispatch_a_medical_tool():
    pipeline = RecordingPipeline()
    status, payload = post_legacy_medical_message(pipeline)

    assert status == 400
    assert payload["error"]["code"] == "INTERACTION_EVENT_REQUIRED"
    assert pipeline.calls == []
```

- [x] **Step 2: Verify shared Core behavior.** In one test process, start a medical task in one session and a cash task in another. Assert task types, workflow-specific views, and no cross-domain facts/actions.

- [x] **Step 3: Verify there is no duplicated medical/cash confirmation, execution, or receipt logic.** Medical confirmation and receipt construction exist only in `medical_workflow.py`. Cash has no confirmation or receipt. Core contains neither implementation. The controller retains only diagnostic `pending_diagnostic`, `_confirm_diagnostic`, `confirm_tool`, diagnostic cancellation, and confirmation-time idempotency.

Run:

```powershell
rg -n "confirmation_decision|create_appointment|receipt_id|ActionReceiptBuilder" middleware/interaction_core.py middleware/controller.py middleware/medical_workflow.py middleware/cash_sharing_workflow.py
```

Expected: domain implementation matches occur only in `medical_workflow.py`; cash contains only the explicit no-receipt TODO/assertion.

- [x] **Step 4: Run all suites independently.** The repository's combined pytest process currently exceeds the timeout, so retain independently green suite evidence rather than claiming a green combined invocation.

Run:

```powershell
& 'C:\Users\steph\AppData\Local\Programs\Python\Python312\python.exe' -m pytest middleware/tests -q
$env:PONTE_ENV_FILE='E:\Steph''s repos\Ponte\missing-test-env'
& 'C:\Users\steph\AppData\Local\Programs\Python\Python312\python.exe' -m pytest tests -q
& 'C:\Users\steph\AppData\Local\Programs\Python\Python312\python.exe' -m pytest MCP/tests -q
node --check frontend/app.js
node --check frontend/interaction-view.js
node --check frontend/voice-exceptions.js
node --check frontend/mcp-client.js
git diff --check
```

Expected: every independent suite and syntax/whitespace check passes.

- [x] **Step 5: Update design documentation from the implemented code.** Revise the existing medical design into the implemented Demo architecture:

```text
Frontend
  → InteractionCore
  → MedicalWorkflow | CashSharingWorkflow
  → ExecutionPipeline (conceptual ToolExecutor; rename deferred)
  → Backend APIs
  → Verified InteractionResult
  → ResponseComposer + WorkspaceProjector
```

Document these implemented ownership rules:

- Core loads/saves task and selects workflow.
- Workflow mutates task and owns domain behavior.
- `ExecutionPipeline` name remains intentionally unchanged for the Demo.
- Medical has verified completion and receipt.
- Cash is verified read-only completion with `receipt: null` and the explicit backend-contract TODO.
- Incomplete backend workflows must not receive invented completion/receipt semantics.
- Legacy elderly-activity/diagnostic support remains until the activity migration.

- [x] **Step 6: Self-review documentation against code.** Search for outdated claims about a medical-aware Core, mandatory receipt generation, deleted activity legacy paths, or a renamed ToolExecutor. Remove placeholders except the intentionally worded backend-contract TODO.

- [x] **Step 7: Commit verification and final documentation.** Stage only intended implementation documentation/tests; keep user-owned dirty files unstaged.

```powershell
git add middleware/tests/test_interaction_architecture.py docs/superpowers/specs/2026-08-06-voice-first-medical-interaction-core-design.md docs/superpowers/plans/2026-08-06-voice-first-medical-interaction-core.md README.md
git commit -m "docs: record implemented demo workflow architecture"
```

## Final Acceptance Criteria

1. `InteractionCore` contains no medical/cash steps, tool names, backend verification, confirmation transition, recovery mapping, or receipt construction.
2. `MedicalWorkflow` owns the complete existing medical query/booking flow and its verified receipt.
3. Medical voice, browser utterance, workspace actions, and assisted events all enter through `EventEnvelope` and `/api/interactions` or the STT adapter to that same Core.
4. Legacy medical message/action requests are rejected before any medical tool execution.
5. `CashSharingWorkflow` runs through the same Core and returns verified safe facts in `cash_sharing_summary`.
6. Cash success has no confirmation, no mutation action, no artifact pretending to be a receipt, and `receipt: null` with the explicit backend-contract TODO.
7. Legacy cash message requests are rejected before the cash tool executes.
8. ResponseComposer and WorkspaceProjector support both medical and cash without frontend inference.
9. No medical/cash confirmation, execution, verification, recovery, or receipt logic remains duplicated in Core or the legacy controller.
10. Elderly activity and MCP diagnostics remain operational on their explicitly temporary legacy surface; deleting the entire legacy controller is deferred until activity migration.
11. `GET /api/mcp/tools`, GET-only `POST /api/mcp/tools/call`, diagnostic confirmation/cancellation, and diagnostic commands naming medical or one-account tools retain their current safety behavior.
12. Middleware, application, MCP, frontend syntax, and whitespace checks pass independently.
13. Architecture/design documentation is updated only after implementation and matches the shipped code.

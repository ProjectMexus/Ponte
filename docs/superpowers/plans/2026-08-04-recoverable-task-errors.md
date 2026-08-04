# Recoverable Task Errors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a middleware Task Manager that turns recoverable backend failures into `awaiting_user_input` task responses with safe recovery guidance and same-task actions.

**Architecture:** Keep `SessionState` as the in-memory session container, but route task lifecycle mutations through a new `middleware/task_manager/` package. `IntentRecognizer`/Intent LLM remains responsible only for user-message intent; the separate `TaskRecoveryInterpreter`/Task Recovery LLM understands sanitized backend/tool results and produces a validated `RecoveryPlan`. `recovery.py` provides the deterministic fallback; `manager.py` applies transitions, records tool results and serializes task responses. The frontend renders recovery guidance inside the existing task card and sends allowed actions through the existing action endpoint.

**Tech Stack:** Python 3 standard library, existing `SessionState`/`ExecutionPipeline`/`ToolExecutionResult` contracts, browser-native JavaScript modules, unittest, `node --check`.

## Global Constraints

- Do not add a real LLM provider or external network dependency.
- Keep Intent LLM and Task Recovery LLM as separate interfaces, prompts, context allowlists, configuration and test doubles; the first implementation uses deterministic recovery fallback behind the Task Recovery LLM interface.
- Do not change existing backend endpoint schemas or existing `retry`, `cancel`, `confirm`, and `human_help` action payloads.
- Do not expose request IDs, tool names, FHIR resource types, internal IDs, raw backend JSON, patient context, or API keys as user-facing text.
- `awaiting_user_input` is non-terminal; `completed`, `cancelled`, `failed`, and `human_handoff` remain terminal.
- A new high-level message resets the current workflow; an action chain must preserve the current workflow data.
- Intent LLM only recognizes user-message intent. Task Recovery LLM only explains sanitized backend/tool results and proposes validated next steps; natural-language continuation remains a future consumer of `continueTask(taskId, input)`.
- Preserve large controls, focus-visible behavior, ARIA labels, high contrast and mobile single-column layout.
- Keep unrelated working-tree changes in `middleware/mcp_client.py`, `middleware/tests/test_mcp_client.py`, and the untracked Windows stdio plan untouched.

---

### Task 1: Add failing lifecycle and recovery contracts

**Files:**
- Create: `middleware/tests/test_task_manager.py`
- Create: `middleware/tests/test_recovery.py`
- Modify: `middleware/tests/test_controller.py`

**Interfaces:**
- Consumes: current `SessionState`, `ToolExecutionResult`, `RecordingPipeline`, and controller workflow.
- Produces: executable regression expectations for `TaskManager`, `RecoveryPlan`, `awaiting_user_input`, empty slots and hard failures.

- [x] **Step 1: Write transition and response tests**

Add tests that import the planned interfaces and specify the public behavior:

```python
from middleware.session import SessionState, build_response
from middleware.task_manager.contracts import RecoveryPlan, RecoveryOption
from middleware.task_manager.transitions import InvalidTaskTransition, ensure_transition


def test_awaiting_user_input_is_not_terminal_and_can_resume():
    ensure_transition("querying", "awaiting_user_input")
    ensure_transition("awaiting_user_input", "selecting_slot")


def test_terminal_task_cannot_resume():
    with self.assertRaises(InvalidTaskTransition):
        ensure_transition("completed", "querying")


def test_recovery_plan_serializes_safe_options():
    plan = RecoveryPlan(
        category="availability",
        reason_code="NO_AVAILABLE_SLOTS",
        explanation="目前沒有可預約名額。",
        options=(RecoveryOption("retry", "重新搜尋", {}),),
    )
    self.assertEqual(plan.to_dict()["options"][0]["action"], "retry")
```

Add a `TaskManagerTests` case that calls `request_user_input()` on a `SessionState`, serializes through `build_response()`, and asserts `task_state == "awaiting_user_input"` plus a non-null `recovery` object.

- [x] **Step 2: Write recovery policy tests**

Define exact fixtures for the four policy categories:

```python
def test_missing_required_field_returns_required_field_plan():
    plan = build_recovery_plan(
        error={"code": "MISSING_REQUIRED_FIELD", "details": {"field": "contact_phone"}},
        step_id="create_appointment",
        workflow="medical_booking",
        data={},
        result_data=None,
        retryable=False,
    )
    self.assertEqual(plan.reason_code, "MISSING_REQUIRED_FIELD")
    self.assertEqual(plan.required_fields[0].name, "contact_phone")


def test_empty_search_result_returns_availability_plan():
    plan = build_recovery_plan(
        error=None,
        step_id="search_slots",
        workflow="medical_booking",
        data={"service_id": "SERVICE-US-001"},
        result_data=[],
        retryable=False,
    )
    self.assertEqual(plan.reason_code, "NO_AVAILABLE_SLOTS")
    self.assertEqual(plan.category, "availability")
```

Also assert retryable backend errors contain `retry`, `cancel`, and `human_help` options, while `BACKEND_INVALID_RESPONSE` returns a hard-failure result rather than a recovery plan.

- [x] **Step 3: Add controller regression tests for same-task recovery**

Extend `RecordingPipeline` with a sequence-capable fake that returns one failed `medical.search_appointment_slots` result followed by a successful result. Add tests asserting:

```python
self.assertEqual(first["task_state"], "awaiting_user_input")
self.assertEqual(first["recovery"]["reason_code"], "BACKEND_TIMEOUT")
self.assertIn("retry", [action["kind"] for action in first["actions"]])

second = controller.handle_action(
    InteractionActionRequest("S-RECOVER", "retry", {})
)
self.assertEqual(second["task_state"], "selecting_slot")
self.assertEqual(second["data"]["service_id"], "SERVICE-US-001")
```

- [x] **Step 4: Run the new tests to confirm the red state**

Run:

```powershell
python -m unittest middleware.tests.test_task_manager middleware.tests.test_recovery middleware.tests.test_controller -v
```

Expected: FAIL because `middleware.task_manager` and the new response/recovery behavior do not exist yet.

- [x] **Step 5: Commit the regression contracts**

```powershell
git add middleware/tests/test_task_manager.py middleware/tests/test_recovery.py middleware/tests/test_controller.py
git commit -m "test: define recoverable task error contracts"
```

### Task 2: Implement Task Manager contracts and transition rules

**Files:**
- Create: `middleware/task_manager/__init__.py`
- Create: `middleware/task_manager/contracts.py`
- Create: `middleware/task_manager/transitions.py`
- Test: `middleware/tests/test_task_manager.py`

**Interfaces:**
- Consumes: Task 1 transition and serialization tests.
- Produces: `RecoveryField`, `RecoveryOption`, `RecoveryPlan`, `TERMINAL_TASK_STATES`, and `ensure_transition(current, target)`.

- [ ] **Step 1: Define serializable recovery value objects**

Implement frozen dataclasses in `contracts.py`:

```python
@dataclass(frozen=True)
class RecoveryField:
    name: str
    label: str
    input_type: str = "text"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True)
class RecoveryOption:
    action: str
    label: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True)
class RecoveryPlan:
    category: str
    reason_code: str
    explanation: str
    required_fields: tuple[RecoveryField, ...] = ()
    options: tuple[RecoveryOption, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError
```

Validate non-empty `category`, `reason_code`, `explanation`, option action/label and mapping payloads in `__post_init__`. `to_dict()` must deep-copy nested values.

- [ ] **Step 2: Define lifecycle constants and allowed transitions**

In `transitions.py`, define:

```python
TERMINAL_TASK_STATES = frozenset({
    "completed", "cancelled", "failed", "human_handoff",
})

class InvalidTaskTransition(ValueError):
    pass

def ensure_transition(current: str, target: str) -> None:
    """Raise InvalidTaskTransition unless target is allowed from current."""
```

Allow the existing workflow transitions plus recovery resume paths. In particular, allow `querying → awaiting_user_input`, `awaiting_user_input → querying`, `awaiting_user_input → selecting_service`, `awaiting_user_input → selecting_slot`, `awaiting_user_input → awaiting_confirmation`, and `awaiting_user_input → cancelled/human_handoff`. Reject every transition out of `completed`, `cancelled`, `failed`, or `human_handoff`.

- [ ] **Step 3: Export the package contract**

Export the value objects and transition helpers from `middleware/task_manager/__init__.py` without importing the controller or HTTP server. Keep package imports free of side effects.

- [ ] **Step 4: Run the focused contract tests**

Run:

```powershell
python -m unittest middleware.tests.test_task_manager -v
```

Expected: PASS for value-object serialization and valid/invalid transitions.

- [ ] **Step 5: Commit the Task Manager contract layer**

```powershell
git add middleware/task_manager middleware/tests/test_task_manager.py
git commit -m "feat: add task manager contracts and transitions"
```

### Task 3: Implement Task Recovery LLM boundary and deterministic recovery policy

**Files:**
- Create: `middleware/task_manager/recovery.py`
- Create: `middleware/task_manager/interpreter.py`
- Test: `middleware/tests/test_recovery.py`

**Interfaces:**
- Consumes: `RecoveryPlan`, `RecoveryField`, `RecoveryOption`, canonical tool error mappings and workflow data.
- Produces: `TaskRecoveryInterpreter` protocol, `DeterministicTaskRecoveryInterpreter`, `build_recovery_plan(error, step_id, workflow, data, result_data, retryable) -> RecoveryPlan | None`, and `is_hard_failure(error) -> bool`.

- [ ] **Step 1: Add canonical reason-code and user-label maps**

Implement allowlists for:

```python
_FIELD_LABELS = {
    "contact_phone": "聯絡電話",
    "identity_document": "身份資料",
    "department_id": "科室選擇",
    "service_id": "服務選擇",
    "slot_id": "預約時段",
}

_RECOVERABLE_CODES = {
    "MISSING_REQUIRED_FIELD",
    "SCHEDULE_FULL",
    "NO_AVAILABLE_SLOTS",
    "BACKEND_UNAVAILABLE",
    "BACKEND_TIMEOUT",
}
```

Unknown field names must use the generic label `必要資料`; never copy an arbitrary backend field name into user-facing text.

- [ ] **Step 2: Define the separate Task Recovery LLM interface**

Create `middleware/task_manager/interpreter.py` with an interface intentionally independent from `middleware/intent.py`:

```python
class TaskRecoveryInterpreter(Protocol):
    def interpret(
        self,
        *,
        error: Mapping[str, Any] | None,
        step_id: str,
        workflow: str,
        data: Mapping[str, Any],
        fallback: RecoveryPlan | None,
    ) -> RecoveryPlan | None:
        raise NotImplementedError


class DeterministicTaskRecoveryInterpreter:
    def interpret(self, *, error, step_id, workflow, data, fallback):
        return fallback
```

The protocol must not import or call `IntentRecognizer`. A future LLM implementation receives only sanitized failure/result context, cannot receive authorization, patient context, raw tool arguments or unapproved backend details, and must validate model output as a `RecoveryPlan` before the manager uses it.

- [ ] **Step 3: Implement missing-data recovery**

For `MISSING_REQUIRED_FIELD`, read only `details.field` or `details.fields` when they are strings from the allowlist; construct `RecoveryField` values and return category `missing_information`. Provide `human_help` and `cancel` options, with explanation `服務中心需要補充資料才能繼續。` when no safer backend text exists.

- [ ] **Step 4: Implement availability recovery**

For `step_id == "search_slots"` and `result_data == []`, return `NO_AVAILABLE_SLOTS` with category `availability`, a retry option and a cancel option. When `error.details.alternatives` or `error.details.available_slots` is a list of mappings, extract only `start`, `end`, `service_name`/`service_display`, `service_id`, and `slot_id`; create user-friendly `select_slot` or `search_slots` options without exposing IDs in labels. Keep payload IDs because the action endpoint needs them.

- [ ] **Step 5: Implement retryable and hard-failure mappings**

For a retryable backend error, return category `temporary_failure` with `retry`, `cancel`, and `human_help` options only when the failed step was safe for retry. For non-retryable create/submit failures, return `None` so the manager marks the task failed. Treat `BACKEND_INVALID_RESPONSE`, `UNKNOWN_TOOL`, permission errors and schema errors as hard failures.

- [ ] **Step 6: Run policy and interpreter separation tests**

Run:

```powershell
python -m unittest middleware.tests.test_recovery -v
```

Add assertions that the deterministic interpreter returns the policy fallback, its module does not import `middleware.intent`, and no plan explanation, label or option label contains `REQ-`, `TOOL`, `LOC-`, `FHIR`, or a raw JSON fragment.

- [ ] **Step 7: Commit the recovery interpreter boundary and policy**

```powershell
git add middleware/task_manager/recovery.py middleware/task_manager/interpreter.py middleware/tests/test_recovery.py
git commit -m "feat: separate task recovery interpretation"
```

### Task 4: Add Task Manager state integration and response serialization

**Files:**
- Modify: `middleware/session.py`
- Create: `middleware/task_manager/manager.py`
- Test: `middleware/tests/test_task_manager.py`

**Interfaces:**
- Consumes: `SessionState`, `ToolExecutionResult`, Task Manager contracts, recovery policy and the separate `TaskRecoveryInterpreter`.
- Produces: `TaskManager(state)` with lifecycle methods used by the controller.

- [ ] **Step 1: Add recovery storage to `SessionState`**

Add:

```python
recovery: dict[str, Any] | None = None
```

Clear it in `reset_for_new_task()`. Include a deep-copied `recovery` field in `build_response()` only when it is not `None`; keep the existing `error` field and all existing response keys unchanged. The serializer must project every `RecoveryOption` from `recovery.options` into the existing action shape `{"kind": option.action, "label": option.label, "payload": option.payload}` so the frontend can execute only the established action contract.

- [ ] **Step 2: Implement lifecycle helpers**

Implement the following methods in `TaskManager`:

```python
class TaskManager:
    def __init__(self, state: SessionState, recovery_interpreter: TaskRecoveryInterpreter | None = None):
        raise NotImplementedError
    def start_new_task(self) -> None:
        raise NotImplementedError
    def start_action(self) -> None:
        raise NotImplementedError
    def transition(self, task_state: str, current_step: str) -> None:
        raise NotImplementedError
    def record_tool_result(
        self,
        result: ToolExecutionResult,
        step_id: str,
        input_data: Mapping[str, Any],
        *,
        safe_for_retry: bool,
        workflow: str,
    ) -> None:
        raise NotImplementedError
    def request_user_input(self, plan: RecoveryPlan) -> None:
        raise NotImplementedError
    def complete(self, current_step: str) -> None:
        raise NotImplementedError
    def cancel(self, current_step: str) -> None:
        raise NotImplementedError
    def human_handoff(self) -> None:
        raise NotImplementedError
    def fail(self, current_step: str, error: Mapping[str, Any], message: str) -> None:
        raise NotImplementedError
```

`record_tool_result()` must append the same safe event shape currently emitted by `_run_tool`, append the step, update `last_tool_call` only when `safe_for_retry` is true, and set a normalized `last_error` on failure. It must not expose raw tool arguments in the `recovery` user text.

- [ ] **Step 3: Apply recovery or hard-failure state**

When `record_tool_result()` receives a failed result, call `build_recovery_plan()` with the current `state.data`, then pass the sanitized context and deterministic fallback to the injected `TaskRecoveryInterpreter`. If the interpreter returns a valid plan, call `request_user_input()` and leave existing workflow data intact. If it returns `None`, call `fail()` and use the existing safe assistant-level failure message supplied by the controller. The default interpreter is deterministic and does not call `IntentRecognizer`.

- [ ] **Step 4: Add manager unit tests**

Assert that:

```python
manager.start_new_task()
manager.transition("querying", "search_slots")
manager.record_tool_result(timeout_result, "search_slots", {"service_id": "SERVICE-US-001"}, safe_for_retry=True, workflow="medical_booking")
self.assertEqual(state.task_state, "awaiting_user_input")
self.assertIsNotNone(state.recovery)
self.assertEqual(state.data["service_id"], "SERVICE-US-001")
```

Also assert `start_action()` clears the previous recovery/error but not services, dates, slots or selected slot; `reset_for_new_task()` clears all workflow transient data; and injecting a fake `TaskRecoveryInterpreter` cannot change intent-recognizer calls.

- [ ] **Step 5: Run focused session and manager tests**

Run:

```powershell
python -m unittest middleware.tests.test_task_manager middleware.tests.test_controller.ControllerTests.test_new_message_resets_previous_workflow_data -v
```

Expected: PASS.

- [ ] **Step 6: Commit the state integration**

```powershell
git add middleware/session.py middleware/task_manager/manager.py middleware/tests/test_task_manager.py
git commit -m "feat: integrate task manager with session state"
```

### Task 5: Route controller workflow and tool results through Task Manager

**Files:**
- Modify: `middleware/controller.py`
- Modify: `middleware/server.py`
- Modify: `middleware/tests/test_controller.py`
- Modify: `tests/test_middleware_integration.py`

**Interfaces:**
- Consumes: `TaskManager` lifecycle methods, `TaskRecoveryInterpreter` and recovery policy.
- Produces: controller responses that keep recoverable backend errors open and allow same-session retry/alternative actions.

- [ ] **Step 1: Start/reset tasks through Task Manager**

Add an optional `recovery_interpreter` constructor parameter to `InteractionController`, `MiddlewareApplication` and `create_application()`, defaulting to `DeterministicTaskRecoveryInterpreter`. At the beginning of `handle_message()`, instantiate `TaskManager(state, self.recovery_interpreter)` and call `start_new_task()`. At the beginning of `handle_action()`, instantiate the same manager and call `start_action()` instead of clearing only `last_error`. Do not call `start_new_task()` from `handle_action()`; do not pass this interpreter through `intent_recognizer`.

- [ ] **Step 2: Replace direct lifecycle assignments in workflow handlers**

Use `manager.transition(task_state, current_step)` for the existing states while leaving intent recognition, tool ordering, data keys and action names unchanged. Keep the existing confirmation rule: `medical.create_appointment` is called only by `confirm` after `awaiting_confirmation`.

- [ ] **Step 3: Delegate `_run_tool()` bookkeeping**

Remove the duplicated event/step/last-error bookkeeping from `_run_tool()` and call:

```python
manager.record_tool_result(
    result,
    step_id,
    input_data,
    safe_for_retry=safe_for_retry,
    workflow=str(state.data.get("intent", "general")),
)
```

Keep `_run_tool()` responsible for constructing `ToolCall` and dispatching the pipeline. Preserve the existing event shape, idempotency behavior and retry safety.

- [ ] **Step 4: Handle empty appointment slots as recoverable**

In `_search_slots()`, after `_result_data()` succeeds, branch on an empty list before setting the normal `selecting_slot` state. Save `state.data["slots"] = []`, apply the availability recovery plan through `TaskManager`, and return an assistant response that explains there are no available slots. If alternatives are supplied by the backend, save the safe candidate list and expose only controlled `select_slot`/`search_slots` actions.

- [ ] **Step 5: Preserve hard schema failures**

Replace `_set_error()` calls for missing `data`, invalid data types, missing task IDs and missing task statuses with `manager.fail()` using `BACKEND_INVALID_RESPONSE`. Keep the current Chinese assistant messages and ensure those responses have `task_state == "failed"` and no recovery actions.

- [ ] **Step 6: Add controller and integration assertions**

Add tests for:

```python
def test_backend_timeout_keeps_booking_task_open(self):
    response = self.controller.handle_action(InteractionActionRequest("S-RECOVER", "retry", {}))
    self.assertEqual(response["task_state"], "awaiting_user_input")


def test_empty_slots_explain_availability_and_keep_task_open(self):
    response = self.controller.handle_action(InteractionActionRequest("S-RECOVER", "retry", {}))
    self.assertEqual(response["recovery"]["reason_code"], "NO_AVAILABLE_SLOTS")


def test_hard_schema_error_remains_failed(self):
    response = self.controller.handle_action(InteractionActionRequest("S-RECOVER", "retry", {}))
    self.assertEqual(response["task_state"], "failed")


def test_retry_after_recoverable_error_reuses_services_and_date_range(self):
    response = self.controller.handle_action(InteractionActionRequest("S-RECOVER", "retry", {}))
    self.assertEqual(response["data"]["service_id"], "SERVICE-US-001")
    self.assertEqual(response["data"]["date_from"], "2026-08-10")
```

Extend the middleware integration flow to submit a same-session recovery action and assert the subsequent tool event list contains the original failed step and the new successful call, while a new high-level message still contains only its own query tool event.

- [ ] **Step 7: Run middleware and integration tests**

Run:

```powershell
python -m unittest middleware.tests.test_controller middleware.tests.test_server tests.test_middleware_integration -v
```

Expected: all existing workflow, diagnostic, reset and new recovery tests pass.

- [ ] **Step 8: Commit controller integration**

```powershell
git add middleware/controller.py middleware/tests/test_controller.py tests/test_middleware_integration.py
git commit -m "feat: keep recoverable workflow errors open"
```

### Task 6: Render recovery guidance in the frontend task workspace

**Files:**
- Modify: `frontend/interaction-view.js`
- Modify: `frontend/styles.css`
- Modify: `tests/test_frontend_static.py`
- Verify: `frontend/app.js`

**Interfaces:**
- Consumes: `TaskResponse.recovery`, `TaskResponse.actions`, and existing `onAction(action, taskId)` routing.
- Produces: accessible recovery panel and same-task recovery action behavior.

- [ ] **Step 1: Add non-terminal state labels and static contracts**

Add `awaiting_user_input` to `TASK_STATE_LABELS` with a friendly label such as `需要你的協助`, and keep it out of `TERMINAL_TASK_STATES`. Add static assertions for the label, the absence of terminal classification, and the `recovery` field handling.

- [ ] **Step 2: Implement `renderRecovery()`**

Add a renderer that creates user-facing text nodes only:

```js
function renderRecovery(container, recovery) {
  if (!recovery || typeof recovery !== "object") return;
  const panel = createElement("section", "recovery-panel");
  panel.setAttribute("role", "status");
  panel.append(createElement("h3", "recovery-title", "下一步怎樣做"));
  if (recovery.explanation) panel.append(createElement("p", "recovery-explanation", recovery.explanation));
  (Array.isArray(recovery.required_fields) ? recovery.required_fields : []).forEach((field) => {
    panel.append(createElement("p", "recovery-field", `需要補充：${field.label || "必要資料"}`));
  });
  container.append(panel);
}
```

Do not render `reason_code`, field `name`, payload values, error details or any unknown recovery object keys. Render actions through the existing `renderActions()` so `onAction(action, task.localId)` remains the only route.

- [ ] **Step 3: Keep recovery cards open and preserve existing actions**

In `renderTaskList()`, append the recovery panel before the action list. Only call `renderActions()` when the response state is not terminal; `awaiting_user_input` must therefore show recovery options. Keep `failTask()` for transport errors and leave global error behavior unchanged.

- [ ] **Step 4: Add responsive recovery styles**

Add `.recovery-panel`, `.recovery-title`, `.recovery-explanation`, and `.recovery-field` styles using existing color variables, focus rules and mobile spacing. Do not shrink existing action controls below their current touch target size.

- [ ] **Step 5: Update frontend static tests and syntax-check**

Add assertions for:

```python
self.assertIn("awaiting_user_input", source)
self.assertIn("renderRecovery", source)
self.assertIn("recovery.explanation", source)
self.assertIn("onAction(action, task.localId)", source)
```

Run:

```powershell
python -m unittest tests.test_frontend_static -v
node --check frontend/app.js
node --check frontend/interaction-view.js
```

- [ ] **Step 6: Commit frontend recovery rendering**

```powershell
git add frontend/interaction-view.js frontend/styles.css tests/test_frontend_static.py
git commit -m "feat: render recoverable task guidance"
```

### Task 7: Synchronize user-facing frontend documentation and run complete verification

**Files:**
- Modify: `frontend/README.md`
- Modify: `README.md`
- Verify: `docs/PonteArch.md`
- Verify: `docs/superpowers/specs/2026-08-04-recoverable-task-errors-design.md`
- Verify: all middleware, frontend, backend and integration tests

**Interfaces:**
- Consumes: completed Task Manager and frontend recovery behavior.
- Produces: accurate user/developer documentation and fresh verification evidence.

- [ ] **Step 1: Document recoverable task behavior**

In `frontend/README.md`, state that recoverable backend errors remain in the task card, show a reason and next-step options, and that completed/hard-failed tasks collapse. State that API/tool identifiers and raw backend JSON are not user-facing. In `README.md`, update the acceptance workflow to mention retrying or choosing alternatives inside the same task card.

- [ ] **Step 2: Run all JavaScript syntax checks**

```powershell
node --check frontend/app.js
node --check frontend/mcp-client.js
node --check frontend/interaction-view.js
node --check frontend/speech.js
```

Expected: all commands exit 0.

- [ ] **Step 3: Run all Python tests and compile checks**

```powershell
python -m unittest discover -v
python -m unittest discover -s MCP/tests -v
python -m unittest discover -s middleware/tests -v
python -m compileall -q MCP middleware mock_backends frontend scripts tests
```

Expected: every unittest command exits 0 and compileall reports no errors.

- [ ] **Step 4: Check docs, identifiers and diff hygiene**

```powershell
git diff --check
rg -n "awaiting_user_input|RecoveryPlan|Task Manager|task_manager|raw backend|tool name" docs/PonteArch.md docs/superpowers/specs/2026-08-04-recoverable-task-errors-design.md docs/superpowers/specs/2026-08-04-task-based-workspace-design.md frontend/README.md README.md
rg -n "REQ-|LOC-|FHIR|tool_name|request_id" frontend/interaction-view.js frontend/styles.css frontend/README.md
```

Expected: architecture and recovery behavior are documented; internal identifiers remain only in non-user-facing mapping or payload code.

- [ ] **Step 5: Run local same-task recovery smoke check**

Start the stack with the existing runner and verify:

1. Begin a medical booking task.
2. Force or simulate a recoverable slot lookup failure; confirm the card stays open and explains the reason.
3. Use the displayed retry or alternative option; confirm the same card advances and preserves service/date context.
4. Complete or cancel the task; confirm it collapses and can be expanded again.
5. Start a new high-level query; confirm the new task does not show stale slots or selected slot data.
6. Check a mobile-width viewport for readable recovery text and keyboard-operable actions.

- [ ] **Step 6: Update this plan with fresh evidence and commit the final implementation**

Record exact test counts, syntax-check results, smoke observations and `git status --short`. Mark the completed checkboxes in this plan with `[x]` only after the commands above succeed. Commit only implementation files belonging to this feature with:

```powershell
git add middleware/task_manager middleware/session.py middleware/controller.py middleware/server.py middleware/tests/test_task_manager.py middleware/tests/test_recovery.py middleware/tests/test_controller.py tests/test_middleware_integration.py frontend/interaction-view.js frontend/styles.css tests/test_frontend_static.py frontend/README.md README.md docs/superpowers/plans/2026-08-04-recoverable-task-errors.md
git commit -m "feat: add recoverable task error workflow"
```

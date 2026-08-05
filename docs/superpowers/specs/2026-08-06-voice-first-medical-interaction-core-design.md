# Voice-first Medical Interaction Core Design

## Purpose

Ponte no longer provides an independent text-input product. Older message-based infrastructure and the newer voice path currently duplicate workflow, confirmation, execution, and receipt responsibilities. This change refactors the reusable semantic capabilities into one channel-independent, task-oriented `InteractionCore`, beginning with the existing medical enquiry and appointment workflow.

ASR text remains an internal semantic representation. It does not make the application a text-chat system, and input modality must not affect workflow execution.

## Scope

This slice covers the existing medical enquiry and appointment workflow, including service discovery, slot selection, confirmation, execution, recovery, completion, and a printable receipt artifact.

It does not yet migrate cash sharing or elderly activities. It also deliberately excludes production-grade task versioning, confirmation expiry, digests, durable execution attempts, complex idempotency, and multiple concurrent active tasks.

The migration is incremental by use case but a hard cutover at the contract boundary. Medical requests use the new event/result contracts directly. The old `/api/interactions/message` and `/api/interactions/action` contracts and old medical workflow path are removed; no compatibility request or response projection is introduced.

## Architecture

```text
Audio input                         Normalized UI or assisted action
    │                                           │
    ▼                                           ▼
STT Adapter                              POST /api/interactions
    │                                           │
    └──────────────► EventEnvelope ◄────────────┘
                            │
                            ▼
                    InteractionCore
                    ├─ intent understanding
                    ├─ task creation and recovery
                    ├─ workflow progression
                    ├─ confirmation handling
                    └─ execution verification
                            │
                            ▼
                 Canonical InteractionResult
                    ├─ ResponseComposer
                    └─ WorkspaceProjector
                            │
                            ▼
                  DeliveryOrchestrator
                    └─ TTS Adapter
                            │
                            ▼
               Unified Interaction Response
```

`POST /api/voice/turn` is an audio input adapter only:

```text
Audio
→ STT Adapter
→ user_utterance EventEnvelope
→ InteractionCore
→ DeliveryOrchestrator
```

`POST /api/interactions` accepts an already normalized `EventEnvelope`. Both endpoints share exactly the same path from `EventEnvelope` onward. There is no voice-specific workflow, execution, confirmation, or receipt path.

## Input Contract

The Core handles an envelope rather than a frontend message:

```json
{
  "routing": {
    "interaction_id": "INT-123",
    "session_id": "SESSION-123"
  },
  "event": {
    "type": "user_utterance",
    "task_id": null,
    "content": "我想預約腹部超聲波"
  },
  "audit": {
    "received_at": "2026-08-06T15:00:00Z"
  }
}
```

`routing` identifies the interaction and session so the Core can load the active task. `event` is the authoritative input. `audit` is observability metadata and is stripped before the Core or explicitly ignored by it; audit fields cannot alter workflow behavior.

`content` is deliberately modality-neutral. `language` and `source: voice` are not part of the Core event. Language may be added later only if the intent/entity interpreter genuinely requires language routing. A first utterance may omit `task_id` or set it to `null`.

Workspace buttons and human-assisted confirmation use the same domain event shape. A server-issued confirmation event includes its complete target:

```json
{
  "type": "confirmation_decision",
  "action_id": "ACT-123",
  "task_id": "TASK-456",
  "confirmation_id": "CONF-789",
  "decision": "approve"
}
```

The frontend returns this event unchanged. It does not construct, complete, or reinterpret the target. `action_id` identifies the server-issued action for the Demo; it does not introduce action versioning or a production idempotency lifecycle.

## Session, Task, and Confirmation State

The Demo assumes one active task per session.

```text
Session
→ active_task_id only

Task
→ status
→ current_step
→ facts
→ pending_confirmation

Confirmation
→ pending | approved | rejected | modified
```

Example task:

```json
{
  "task_id": "TASK-456",
  "type": "medical_appointment",
  "status": "awaiting_confirmation",
  "current_step": "confirm_appointment",
  "facts": {
    "service_id": "SERVICE-US-001",
    "slot_id": "SLOT-US-20260807-1500"
  },
  "pending_confirmation": {
    "confirmation_id": "CONF-789",
    "status": "pending"
  }
}
```

For a confirmation decision, the Core checks only that:

- the task exists;
- the confirmation ID matches the task's pending confirmation;
- the confirmation is still `pending`;
- the decision is `approve`, `reject`, or `modify`.

Transitions are:

```text
approve
→ confirmation approved
→ task executing
→ ExecutionPipeline

reject
→ confirmation rejected
→ task cancelled

modify
→ confirmation modified
→ task awaiting_input
→ return to service or slot selection
```

The minimal double-submit guard is:

```text
confirmation.status != pending
→ do not execute again
→ return the current task result
```

The interaction log may be an in-memory list containing only major events:

```text
user_utterance
service_selected
slot_selected
confirmation_requested
confirmation_decision
execution_completed
receipt_created
```

## Execution, Verification, Recovery, and Receipt Ownership

`ExecutionPipeline` executes a tool and returns a unified `ToolExecutionResult`. It knows whether the tool call returned successfully, but it does not know whether an appointment is complete in business terms.

The `InteractionCore` owns domain completion:

```text
approve
→ confirmation approved
→ task executing
→ ExecutionPipeline.dispatch()
→ validate medical result
→ extract verified user-safe facts
→ ActionReceiptBuilder
→ task completed
→ attach receipt
→ Canonical InteractionResult
```

The medical verifier requires a successful tool result and the appointment, task, and backend receipt fields needed to prove completion. Only after verification succeeds may the Core extract safe facts and build a receipt. The task is marked `completed` only after receipt construction succeeds.

`ActionReceiptBuilder` accepts verified safe facts only. It cannot consume raw tool requests, raw backend payloads, internal request IDs, or patient identifiers. A canonical medical receipt is:

```json
{
  "receipt_id": "MED-APT-88219",
  "kind": "medical_appointment",
  "status": "completed",
  "issued_at": "2026-08-06T15:01:00Z",
  "task_id": "TASK-456",
  "appointment": {
    "service": "腹部超聲波檢查",
    "date": "2026-08-07",
    "time": "15:00",
    "location": "景湖醫療中心",
    "status": "confirmed"
  }
}
```

`receipt_id` and `issued_at` directly reuse the verified backend business receipt. There is no second `reference` field.

The backend currently requires an idempotency key. For this Demo, execution derives one stable value from `confirmation_id`; this is only enough to avoid accidental duplicate appointment creation and does not add a broader idempotency model.

Recoverable failures do not create receipts:

```text
tool or backend failure
→ map domain-safe failure reason
→ task awaiting_input
→ expose allowed recovery actions
→ no receipt
```

An invalid backend response is represented as:

```json
{
  "status": "awaiting_input",
  "recovery": {
    "reason": "invalid_backend_response",
    "allowed_actions": ["retry", "human_help", "cancel"]
  }
}
```

Only unrecoverable program errors use `failed`. Expected medical recovery mappings include slot unavailable, duplicate appointment, missing referral, and temporary backend unavailability. The Core maps these to deterministic next steps such as choosing another slot, supplying required information, retrying, requesting human help, or cancelling.

## Canonical Interaction Result

The Core produces task-centered data, not final prose or frontend component instructions. A confirmation result contains enough authoritative state for downstream projection:

```json
{
  "interaction_id": "INT-123",
  "task": {
    "task_id": "TASK-456",
    "type": "medical_appointment",
    "status": "awaiting_confirmation",
    "current_step": "confirm_appointment"
  },
  "response_intent": "request_confirmation",
  "facts": {
    "service": "腹部超聲波檢查",
    "date": "2026-08-07",
    "time": "15:00",
    "location": "景湖醫療中心"
  },
  "confirmation": {
    "confirmation_id": "CONF-789",
    "status": "pending"
  },
  "allowed_actions": [
    {
      "type": "confirmation_decision",
      "action_id": "ACT-123",
      "task_id": "TASK-456",
      "confirmation_id": "CONF-789",
      "decision": "approve"
    }
  ],
  "receipt": null
}
```

The canonical result excludes:

- final display or speech prose;
- audio;
- HTML;
- frontend component structures;
- raw tool or backend data;
- input or delivery channel metadata.

## Response Composer

`ResponseComposer.compose(interaction_result)` produces only:

```json
{
  "display_text": "已找到以下時段，請確認預約資料。",
  "speech_text": "我搵到呢個時段。日期係八月七號下晝三點，請問係咪確認預約？"
}
```

It receives only the response intent, verified safe facts, task status, allowed action meanings, and expression constraints such as reading back critical details. It may adjust phrasing, simplify explanations, and produce natural Cantonese speech.

It cannot change business facts or task state, add actions, claim an unverified completion, build or modify a receipt, choose the workspace view, or access raw backend/tool data.

The LLM interface is separate from intent and recovery interpretation. Its output is schema-constrained to `display_text` and `speech_text`. Timeout, provider error, invalid structure, empty output, or output violating configured limits uses deterministic templates. Composer failure never changes the task result.

## Workspace Projector

`WorkspaceProjector.project(interaction_result)` is deterministic and does not depend on the Response Composer. It converts canonical facts into display-ready fields and server-issued actions:

```json
{
  "view": "appointment_confirmation",
  "title": "確認醫療預約",
  "fields": [
    {
      "label": "服務",
      "value": "腹部超聲波檢查"
    },
    {
      "label": "日期",
      "value": "2026年8月7日"
    },
    {
      "label": "時間",
      "value": "下午3:00"
    }
  ],
  "actions": [
    {
      "label": "確認預約",
      "event": {
        "type": "confirmation_decision",
        "action_id": "ACT-123",
        "task_id": "TASK-456",
        "confirmation_id": "CONF-789",
        "decision": "approve"
      }
    }
  ],
  "artifact": null
}
```

The first medical slice supports these views:

```text
appointment_list
service_selection
slot_selection
appointment_confirmation
appointment_recovery
appointment_completed
```

The projector adds deterministic display labels and formatting, but copies each complete action target issued by the Core. The frontend submits the `event` unchanged.

## Delivery and TTS

`DeliveryOrchestrator` combines the canonical result, composed response, projected workspace, and TTS delivery status:

```json
{
  "interaction_id": "INT-123",
  "task": {
    "task_id": "TASK-456",
    "type": "medical_appointment",
    "status": "awaiting_confirmation",
    "current_step": "confirm_appointment"
  },
  "response": {
    "display_text": "已找到以下時段，請確認預約資料。",
    "speech_text": "我搵到呢個時段，請問係咪確認預約？"
  },
  "workspace": {
    "view": "appointment_confirmation",
    "title": "確認醫療預約",
    "fields": [],
    "actions": [],
    "artifact": null
  },
  "confirmation": {
    "confirmation_id": "CONF-789",
    "status": "pending"
  },
  "receipt": null,
  "speech_audio": {
    "status": "ready",
    "url": "/api/audio/INT-123"
  }
}
```

TTS failure is a delivery failure and cannot alter task, confirmation, workspace, or receipt state. The server reports `speech_audio.status` as `ready` or `unavailable`. Browser speech fallback belongs exclusively to frontend delivery logic:

```text
speech_audio.status == ready
→ play server TTS

speech_audio.status == unavailable
→ use response.speech_text
→ browser speech synthesis
```

Neither the Core nor the Workspace Projector knows about this fallback.

## Frontend Responsibilities

The frontend retains one rendering and event-submission path:

```text
Unified Interaction Response
├─ response.display_text → visible response
├─ speech_audio           → server audio or frontend fallback
├─ workspace.view         → deterministic view selection
├─ workspace.fields       → generic field rendering
├─ workspace.actions      → generic action rendering
└─ receipt                → artifact rendering and printing
```

The frontend must not infer workflow state from prose, parse dates or services from response text, use regular expressions to decide the next step, construct confirmation context, or fill missing receipt fields. Text is communication only; the workspace model controls the UI.

The duplicated workflow rendering currently split across interaction and voice-specific frontend code is reduced to one renderer. Voice-specific frontend code may remain only for audio transport and delivery errors, not for business workflow behavior.

Legacy response fields are removed:

```text
assistant_message
assistant_speech_message
task_state
current_step
top-level data / actions
```

The receipt artifact renderer consumes the canonical receipt and produces HTML locally for display, download, and printing. No LLM, Core component, tool adapter, or backend supplies receipt HTML.

## Error Boundaries

Error ownership follows the component boundary:

- input adapters report audio or envelope validation failures;
- the Core reports domain validation and recoverable workflow results;
- the Execution Pipeline reports tool transport and execution results without declaring business completion;
- the medical verifier determines whether backend data proves completion;
- the Response Composer falls back to deterministic wording;
- the TTS adapter reports delivery availability;
- the Workspace Projector always renders from authoritative canonical data and never repairs it by inference.

No failed or invalid execution produces a receipt or a completion claim.

## Testing Strategy

Tests are organized around contracts and ownership boundaries.

### Interaction Core

- A first `user_utterance` with no task ID creates or locates the medical task.
- Service and slot selection advance deterministic task steps.
- Voice, workspace button, and human-assisted decisions normalize to the same confirmation event.
- Approve, reject, and modify produce the defined state transitions.
- A non-pending confirmation returns current state without executing again.
- A mismatched task or confirmation target is rejected.

### Execution and Receipt

- Tool success alone does not complete a task.
- A valid medical backend result is verified before receipt construction and completion.
- Invalid backend data leads to `awaiting_input`, recovery actions, and no receipt.
- Backend business receipt values become `receipt_id` and `issued_at` exactly once.
- Receipt facts contain no raw backend payload, internal request ID, or patient identifier.
- Repeating an approved confirmation does not create a second appointment.

### Projection and Delivery

- Composer output cannot alter task facts, actions, or receipt data.
- Invalid composer output uses deterministic display and speech templates.
- Workspace projection is identical regardless of composer wording or failure.
- Projected actions include complete server-issued targets, including `action_id`.
- TTS failure leaves Core and workspace results unchanged.

### Frontend

- Each medical `workspace.view` renders without inspecting response prose.
- Buttons submit the supplied event object unchanged.
- Server audio plays when ready; unavailable audio uses `response.speech_text` locally.
- A completed canonical receipt renders as an artifact and prints successfully.
- Recovery views render from structured recovery data without natural-language parsing.

### End-to-End

- `/api/voice/turn` and `/api/interactions` produce equivalent workflow outcomes from equivalent normalized events.
- The complete existing medical path reaches service selection, slot selection, confirmation, verified execution, completion, and a printable receipt.
- Expected backend failures return deterministic recovery UI and never claim completion.

## Acceptance Criteria

The medical migration is complete when:

1. All medical input reaches one `InteractionCore` through an `EventEnvelope`.
2. The voice endpoint contains no separate medical workflow, confirmation, execution, or receipt logic.
3. Session, task, and confirmation follow the simplified Demo model.
4. The Core, not the Execution Pipeline, verifies business completion.
5. A receipt is successfully built from verified safe facts before the task becomes completed, then attached in the same Core handler.
6. Response wording cannot control workflow or workspace behavior.
7. Workspace actions contain complete server-issued targets and are submitted unchanged.
8. The frontend contains no natural-language workflow parsing.
9. TTS and browser speech fallback are delivery concerns only.
10. The completed medical workflow produces a printable canonical receipt artifact.

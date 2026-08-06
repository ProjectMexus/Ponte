import unittest

from middleware.cash_sharing_workflow import CashSharingWorkflow
from middleware.contracts import ToolExecutionResult
from middleware.intent import IntentDecision
from middleware.interaction_contracts import EventEnvelope


def plan_payload(**overrides):
    plan = {
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
    }
    plan.update(overrides)
    return {"plan": plan, "history": []}


class FakeCashPipeline:
    def __init__(self, *, data=None, failures=0):
        self.calls = []
        self.data = data
        self.failures = failures

    def dispatch(self, call):
        self.calls.append(call)
        if call.name != "one_account.get_cash_sharing_plan":
            raise AssertionError(f"unexpected tool: {call.name}")
        if self.failures > 0:
            self.failures -= 1
            return ToolExecutionResult(
                call.name,
                call.step_id,
                False,
                "REQ-FAIL",
                None,
                {"code": "BACKEND_TIMEOUT", "message": "backend timeout", "retryable": True},
            )
        return ToolExecutionResult(
            call.name,
            call.step_id,
            True,
            "REQ-PLAN",
            {"request_id": "REQ-PLAN", "data": plan_payload() if self.data is None else self.data},
        )


def envelope(session_id, interaction_id, event):
    return EventEnvelope.from_json({
        "routing": {"session_id": session_id, "interaction_id": interaction_id},
        "event": event,
    })


def cash_intent():
    return IntentDecision("cash_sharing", "keyword", 1.0)


class CashSharingWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.pipeline = FakeCashPipeline()
        self.workflow = CashSharingWorkflow(
            self.pipeline,
            patient_id="PAT-DEMO-001",
            authorization="Bearer demo",
            mock_user_id="USR-DEMO-001",
        )

    def start(self, session_id="S-CASH", interaction_id="INT-CASH-1"):
        return self.workflow.start(
            envelope(session_id, interaction_id, {
                "type": "user_utterance",
                "task_id": None,
                "content": "我想查現金分享計劃",
            }),
            cash_intent(),
        )

    def recovery_action(self, task, action, interaction_id="INT-CASH-2"):
        return self.workflow.handle(task, envelope("S-CASH", interaction_id, {
            "type": "recovery_action",
            "action_id": "ACT-RECOVERY",
            "task_id": task["task_id"],
            "action": action,
        }))

    def test_cash_query_completes_with_verified_facts_and_no_receipt(self):
        task, result, _ = self.start()

        self.assertEqual(task["type"], "cash_sharing_query")
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["current_step"], "complete")
        self.assertEqual(result.response_intent, "cash_sharing_summary")
        self.assertEqual(result.facts["plan"]["plan_id"], "CSP-2026")
        self.assertEqual(result.facts["plan"]["plan_name"], "現金分享計劃")
        self.assertEqual(result.facts["plan"]["year"], 2026)
        self.assertEqual(result.facts["plan"]["status"], "OPEN")
        self.assertEqual(result.facts["plan"]["eligibility"]["eligible"], True)
        self.assertEqual(result.facts["plan"]["payout"]["amount"], 10000)
        self.assertEqual(result.facts["plan"]["payout"]["currency"], "MOP")
        self.assertEqual(result.facts["history"], [])
        self.assertIsNone(result.receipt)
        self.assertIsNone(task["receipt"])
        self.assertIsNone(result.confirmation)
        self.assertEqual(result.allowed_actions, [])
        self.assertEqual(result.recovery, None)
        self.assertEqual(
            [call.name for call in self.pipeline.calls],
            ["one_account.get_cash_sharing_plan"],
        )
        self.assertEqual(self.pipeline.calls[0].arguments["input"], {})

    def test_cash_facts_exclude_transport_and_user_identifiers(self):
        task, result, _ = self.start()

        self.assertEqual(set(result.facts), {"plan", "history"})
        forbidden = {
            "request_id", "mock_user_id", "patient_id", "authorization",
            "idempotency_key", "accept_language", "context",
        }
        self.assertFalse(forbidden & set(result.facts))
        self.assertFalse(forbidden & set(result.facts["plan"]))
        self.assertFalse(forbidden & set(result.facts["plan"]["eligibility"]))
        self.assertFalse(forbidden & set(result.facts["plan"]["payout"]))
        self.assertFalse(forbidden & set(task))

    def test_cash_malformed_backend_result_enters_recovery(self):
        bad_payloads = (
            {},
            {"plan": {k: v for k, v in plan_payload()["plan"].items() if k != "plan_id"}, "history": []},
            {"plan": dict(plan_payload()["plan"], year="2026"), "history": []},
            {"plan": dict(plan_payload()["plan"], payout={"amount": "10000", "currency": "MOP"}), "history": []},
            {"plan": dict(plan_payload()["plan"], eligibility={"eligible": "yes"}), "history": []},
            {"plan": dict(plan_payload()["plan"], plan_name=""), "history": []},
        )
        for payload in bad_payloads:
            pipeline = FakeCashPipeline(data=payload)
            workflow = CashSharingWorkflow(
                pipeline,
                patient_id="PAT-DEMO-001",
                authorization="Bearer demo",
            )
            task, result, _ = workflow.start(
                envelope("S-CASH-BAD", "INT-CASH-BAD", {
                    "type": "user_utterance",
                    "task_id": None,
                    "content": "我想查現金分享計劃",
                }),
                cash_intent(),
            )
            self.assertEqual(task["status"], "awaiting_input", payload)
            self.assertEqual(task["current_step"], "load_cash_sharing_plan", payload)
            self.assertEqual(result.response_intent, "cash_sharing_recovery", payload)
            self.assertEqual(result.recovery["reason"], "invalid_backend_response", payload)
            self.assertIsNone(result.receipt, payload)
            self.assertIsNone(result.confirmation, payload)
            self.assertEqual(
                [action["event"]["action"] for action in result.allowed_actions],
                ["retry", "human_help", "cancel"],
                payload,
            )

    def test_cash_backend_failure_enters_recovery_and_retry_completes(self):
        pipeline = FakeCashPipeline(failures=1)
        workflow = CashSharingWorkflow(
            pipeline,
            patient_id="PAT-DEMO-001",
            authorization="Bearer demo",
        )
        task, result, _ = workflow.start(
            envelope("S-CASH-RETRY", "INT-CASH-RETRY", {
                "type": "user_utterance",
                "task_id": None,
                "content": "我想查現金分享計劃",
            }),
            cash_intent(),
        )
        self.assertEqual(task["status"], "awaiting_input")
        self.assertEqual(result.response_intent, "cash_sharing_recovery")
        self.assertEqual(result.recovery["reason"], "backend_unavailable")
        self.assertEqual(
            [action["event"]["action"] for action in result.allowed_actions],
            ["retry", "human_help", "cancel"],
        )
        for action in result.allowed_actions:
            self.assertEqual(action["event"]["type"], "recovery_action")
            self.assertEqual(action["event"]["task_id"], task["task_id"])

        recovered, retry_result, _ = workflow.handle(task, envelope("S-CASH-RETRY", "INT-CASH-RETRY-2", {
            "type": "recovery_action",
            "action_id": "ACT-RETRY",
            "task_id": task["task_id"],
            "action": "retry",
        }))
        self.assertEqual(recovered["status"], "completed")
        self.assertEqual(recovered["current_step"], "complete")
        self.assertEqual(retry_result.response_intent, "cash_sharing_summary")
        self.assertEqual(retry_result.facts["plan"]["plan_id"], "CSP-2026")
        self.assertIsNone(retry_result.receipt)
        self.assertEqual(len(pipeline.calls), 2)

    def test_cash_recovery_cancel_leaves_task_cancelled(self):
        pipeline = FakeCashPipeline(failures=1)
        workflow = CashSharingWorkflow(
            pipeline,
            patient_id="PAT-DEMO-001",
            authorization="Bearer demo",
        )
        task, _, _ = workflow.start(
            envelope("S-CASH-CANCEL", "INT-CASH-CANCEL", {
                "type": "user_utterance",
                "task_id": None,
                "content": "我想查現金分享計劃",
            }),
            cash_intent(),
        )
        cancelled, result, _ = self.workflow_cancel(workflow, task)
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(result.response_intent, "cancelled")
        self.assertIsNone(result.recovery)
        self.assertEqual(len(pipeline.calls), 1)

    @staticmethod
    def workflow_cancel(workflow, task):
        return workflow.handle(task, envelope("S-CASH-CANCEL", "INT-CASH-CANCEL-2", {
            "type": "recovery_action",
            "action_id": "ACT-CANCEL",
            "task_id": task["task_id"],
            "action": "cancel",
        }))

    def test_cash_recovery_human_help_keeps_task_open(self):
        pipeline = FakeCashPipeline(failures=1)
        workflow = CashSharingWorkflow(
            pipeline,
            patient_id="PAT-DEMO-001",
            authorization="Bearer demo",
        )
        task, _, _ = workflow.start(
            envelope("S-CASH-HELP", "INT-CASH-HELP", {
                "type": "user_utterance",
                "task_id": None,
                "content": "我想查現金分享計劃",
            }),
            cash_intent(),
        )
        helped, result, _ = workflow.handle(task, envelope("S-CASH-HELP", "INT-CASH-HELP-2", {
            "type": "recovery_action",
            "action_id": "ACT-HELP",
            "task_id": task["task_id"],
            "action": "human_help",
        }))
        self.assertEqual(helped["status"], "awaiting_input")
        self.assertEqual(result.response_intent, "cash_sharing_recovery")
        self.assertEqual(result.recovery["reason"], "human_help_requested")
        self.assertEqual(
            [action["event"]["action"] for action in result.allowed_actions],
            ["cancel"],
        )

    def test_cash_optional_fields_are_omitted_when_unusable(self):
        plan = plan_payload()["plan"]
        plan["payout"]["scheduled_date"] = 20260930
        plan["eligibility"].pop("reason")
        plan.pop("last_updated_at")
        pipeline = FakeCashPipeline(data={"plan": plan, "history": [{"bad": True}]})
        workflow = CashSharingWorkflow(
            pipeline,
            patient_id="PAT-DEMO-001",
            authorization="Bearer demo",
        )
        task, result, _ = workflow.start(
            envelope("S-CASH-OPT", "INT-CASH-OPT", {
                "type": "user_utterance",
                "task_id": None,
                "content": "我想查現金分享計劃",
            }),
            cash_intent(),
        )
        self.assertEqual(task["status"], "completed")
        self.assertNotIn("scheduled_date", result.facts["plan"]["payout"])
        self.assertNotIn("reason", result.facts["plan"]["eligibility"])
        self.assertNotIn("last_updated_at", result.facts["plan"])
        self.assertEqual(result.facts["history"], [])

    def test_cash_start_requires_utterance_and_cash_intent(self):
        with self.assertRaises(ValueError):
            self.workflow.start(
                envelope("S-CASH", "INT-CASH-E1", {
                    "type": "recovery_action",
                    "action_id": "ACT-1",
                    "task_id": "TASK-1",
                    "action": "retry",
                }),
                cash_intent(),
            )
        with self.assertRaises(ValueError):
            self.workflow.start(
                envelope("S-CASH", "INT-CASH-E2", {
                    "type": "user_utterance",
                    "task_id": None,
                    "content": "我想預約醫療服務",
                }),
                IntentDecision("medical_booking", "keyword", 1.0),
            )

    def test_cash_handle_rejects_unknown_events(self):
        task, _, _ = self.start()
        with self.assertRaises(ValueError):
            self.workflow.handle(task, envelope("S-CASH", "INT-CASH-E3", {
                "type": "slot_selected",
                "action_id": "ACT-1",
                "task_id": task["task_id"],
                "slot_id": "SLOT-1",
            }))

    def test_cash_retry_requires_matching_task(self):
        pipeline = FakeCashPipeline(failures=1)
        workflow = CashSharingWorkflow(
            pipeline,
            patient_id="PAT-DEMO-001",
            authorization="Bearer demo",
        )
        task, _, _ = workflow.start(
            envelope("S-CASH-MATCH", "INT-CASH-MATCH", {
                "type": "user_utterance",
                "task_id": None,
                "content": "我想查現金分享計劃",
            }),
            cash_intent(),
        )
        with self.assertRaises(ValueError):
            workflow.handle(task, envelope("S-CASH-MATCH", "INT-CASH-MATCH-2", {
                "type": "recovery_action",
                "action_id": "ACT-RETRY",
                "task_id": "TASK-OTHER",
                "action": "retry",
            }))


if __name__ == "__main__":
    unittest.main()

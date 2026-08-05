"""Isolated approval classification and pending-proposal resolution."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from .agent import ContextualExecutor
from .contracts import (
    ApprovalClassification,
    ApprovalResolution,
    PendingToolProposal,
    ToolCall,
)
from .llm_transport import ChatCompletionClient, strict_json_content


class ApprovalClassifier:
    """Classify one confirmation utterance without conversational history."""

    SYSTEM_PROMPT = (
        "Classify only the user's current confirmation utterance. Return one strict JSON object "
        'with exactly {"decision":"APPROVE|CANCEL|UNCERTAIN","confidence":0.0}. '
        "APPROVE requires a clear affirmative instruction, CANCEL requires a clear rejection, "
        "and ambiguous, conditional, unrelated, or conflicting language is UNCERTAIN."
    )

    def __init__(self, client: ChatCompletionClient, *, confidence_threshold: float = 0.9) -> None:
        if isinstance(confidence_threshold, bool) or not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be between 0 and 1")
        self.client = client
        self.confidence_threshold = float(confidence_threshold)

    def classify(self, user_message: str) -> ApprovalClassification:
        if not isinstance(user_message, str) or not user_message.strip():
            return ApprovalClassification("UNCERTAIN", 0.0)
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_message.strip()},
        ]
        try:
            response = self.client.complete(
                messages,
                response_format={"type": "json_object"},
                temperature=0,
            )
            payload = response if "decision" in response else strict_json_content(response)
            if set(payload) != {"decision", "confidence"}:
                raise ValueError("approval payload has unexpected fields")
            decision = payload.get("decision")
            confidence = payload.get("confidence")
            if decision not in ("APPROVE", "CANCEL", "UNCERTAIN"):
                raise ValueError("unsupported approval decision")
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                raise ValueError("approval confidence must be numeric")
            normalized_confidence = float(confidence)
            if not 0.0 <= normalized_confidence <= 1.0:
                raise ValueError("approval confidence must be between 0 and 1")
            if normalized_confidence < self.confidence_threshold:
                return ApprovalClassification("UNCERTAIN", normalized_confidence)
            return ApprovalClassification(decision, normalized_confidence)
        except Exception:
            return ApprovalClassification("UNCERTAIN", 0.0)


class ApprovalGate:
    """Resolve a confirmation against one exact stored proposal."""

    def __init__(
        self,
        classifier: ApprovalClassifier,
        executor: ContextualExecutor,
        *,
        clock: Any = time.time,
    ) -> None:
        self.classifier = classifier
        self.executor = executor
        self.clock = clock

    def resolve(
        self,
        user_message: str,
        pending_proposal: PendingToolProposal,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> ApprovalResolution:
        if not isinstance(pending_proposal, PendingToolProposal):
            return ApprovalResolution("invalid", None, None)
        if not pending_proposal.verify_integrity():
            return ApprovalResolution("invalid", None, None)
        if pending_proposal.is_expired(self.clock()):
            return ApprovalResolution("expired", None, None)

        classification = self.classifier.classify(user_message)
        if classification.decision == "CANCEL":
            return ApprovalResolution("cancelled", classification, None)
        if classification.decision == "UNCERTAIN":
            return ApprovalResolution("uncertain", classification, pending_proposal)

        call = ToolCall(
            pending_proposal.tool_name,
            pending_proposal.tool_arguments(),
            f"approval-{pending_proposal.proposal_id}",
        )
        result = self.executor.dispatch(call, dict(context or {}))
        return ApprovalResolution("executed", classification, None, result)

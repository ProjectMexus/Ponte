"""Public package surface for Ponte's frontend-facing middleware."""

from .contracts import (
    AgentRunResult,
    ApprovalClassification,
    ApprovalResolution,
    InteractionActionRequest,
    InteractionRequest,
    PendingToolProposal,
    ToolCall,
    ToolExecutionResult,
)
from .agent import RegistryDrivenAgent, project_registry_tools
from .approval import ApprovalClassifier, ApprovalGate
from .execution import ContextualExecutionPipeline
from .llm_transport import OpenAICompatibleChatClient
from .intent import (
    HybridIntentRecognizer,
    IntentDecision,
    IntentRecognizer,
    IntentRecognitionError,
    KeywordIntentRecognizer,
    LlmIntentRecognizer,
    build_intent_recognizer,
)
from .session import SessionState, SessionStore, build_response

__all__ = [
    "InteractionActionRequest",
    "InteractionRequest",
    "AgentRunResult",
    "ApprovalClassification",
    "ApprovalResolution",
    "ApprovalClassifier",
    "ApprovalGate",
    "ContextualExecutionPipeline",
    "HybridIntentRecognizer",
    "IntentDecision",
    "IntentRecognizer",
    "IntentRecognitionError",
    "KeywordIntentRecognizer",
    "LlmIntentRecognizer",
    "OpenAICompatibleChatClient",
    "PendingToolProposal",
    "RegistryDrivenAgent",
    "SessionState",
    "SessionStore",
    "ToolCall",
    "ToolExecutionResult",
    "build_intent_recognizer",
    "build_response",
    "project_registry_tools",
]

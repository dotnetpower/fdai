"""Process-local chat request preparation outside HTTP transport.

Responsibility: Validate and assemble one bounded chat request for conversation execution.
Boundary: Accept server-authenticated request data and return typed preparation outcomes.
Authority and state: Holds no approval or execution authority and writes only through
injected stores.
Dependencies: Uses conversation policies, evidence resolvers, and principal-scoped history
providers.
Deployment: Runs in-process with the Operator API and creates no network boundary.
"""

from .content_policy import (
    AnswerInvoker,
    StreamInvoker,
    answer_with_content_policy_recovery,
    collect_stream_with_content_policy_recovery,
)
from .document_evidence import (
    ChatDocumentEvidenceResolver,
    ChatDocumentRef,
    parse_document_refs,
    resolve_document_refs,
)
from .history import (
    DEFAULT_CHAT_HISTORY_POLICY,
    BackendChatHistoryCompressor,
    ChatHistoryCompressor,
    ChatHistoryPolicy,
    ResolvedChatHistory,
    compact_history_for_content_policy,
    resolve_chat_history,
    resolve_chat_history_result,
)
from .identity import (
    DEFAULT_MAX_SESSION_ID_CHARS,
    AnswerPreferenceResolver,
    ModelPreferenceResolver,
    parse_conversation_context,
    resolve_request_id,
    resolve_session_id,
    resolve_target_agent,
)
from .replay import content_policy_replay_stage
from .resource_context import (
    contextualize_resource_followup,
    missing_read_investigation_context_evidence,
    parse_resource_context,
)
from .service import (
    ChatContentRejectedError,
    ChatDocumentAccessDeniedError,
    ChatDocumentEvidenceUnavailableError,
    ChatRequestConflictError,
    ChatRequestPreparationInput,
    ContentPolicyReplayRequest,
    InvalidChatRequestError,
    PreparedChatStreamRequest,
    prepare_chat_request,
)

__all__ = [
    "AnswerInvoker",
    "AnswerPreferenceResolver",
    "BackendChatHistoryCompressor",
    "ChatContentRejectedError",
    "ChatDocumentAccessDeniedError",
    "ChatDocumentEvidenceResolver",
    "ChatDocumentRef",
    "ChatDocumentEvidenceUnavailableError",
    "ChatHistoryCompressor",
    "ChatHistoryPolicy",
    "ChatRequestConflictError",
    "ChatRequestPreparationInput",
    "ContentPolicyReplayRequest",
    "DEFAULT_CHAT_HISTORY_POLICY",
    "DEFAULT_MAX_SESSION_ID_CHARS",
    "InvalidChatRequestError",
    "ModelPreferenceResolver",
    "PreparedChatStreamRequest",
    "ResolvedChatHistory",
    "StreamInvoker",
    "answer_with_content_policy_recovery",
    "collect_stream_with_content_policy_recovery",
    "compact_history_for_content_policy",
    "content_policy_replay_stage",
    "contextualize_resource_followup",
    "missing_read_investigation_context_evidence",
    "parse_conversation_context",
    "parse_document_refs",
    "parse_resource_context",
    "prepare_chat_request",
    "resolve_chat_history",
    "resolve_chat_history_result",
    "resolve_document_refs",
    "resolve_request_id",
    "resolve_session_id",
    "resolve_target_agent",
]

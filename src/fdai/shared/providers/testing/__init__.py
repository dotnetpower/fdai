"""In-memory fakes for the four CSP-neutrality Protocols.

Shipped in the main package (not under ``tests/``) so:

- Unit tests import them directly (no ``tests/`` -> ``src/`` reach-through).
- Debugger sessions can `from fdai.shared.providers.testing import
  InMemoryEventBus` and run the loop offline.
- A future ``DevContainer`` composition root can wire these in for a "no
  Docker" run of the stack.

Nothing in this package is production-safe - mutations vanish on process
restart. The real Postgres + Kafka adapters land with W1.5 and W6.3.
"""

from .blast_probe import NoOpBlastProbe
from .break_glass_pager import InMemoryBreakGlassPager
from .briefing import (
    InMemoryBriefingRunStore,
    InMemoryBriefingSubscriptionStore,
    InMemoryConversationPolicyStore,
)
from .command_runner import RecordingCommandRunner
from .conversation_search import InMemoryConversationSearch
from .direct_api import RecordingDirectApiExecutor
from .document_ingestion import (
    InMemoryDocumentAccessProvider,
    InMemoryDocumentArtifactStore,
    InMemoryDocumentIndex,
    InMemoryDocumentMetadataStore,
    InMemoryDocumentObjectStore,
    RecordingDocumentActivitySink,
    StaticMalwareScanner,
)
from .event_bus import InMemoryEventBus
from .hil_registry import InMemoryHilApprovalRegistry
from .live_event_bus import LiveInMemoryEventBus
from .ontology_instance import InMemoryOntologyInstanceStore
from .process_runtime import InMemoryProcessRuntimeStore
from .remediation_pr import RecordingRemediationPrPublisher
from .runbook_registry import InMemoryRunbookRegistry
from .secret_provider import InMemorySecretProvider
from .sse import InMemorySseSink
from .stage_publisher import RecordingStagePublisher
from .state_store import InMemoryStateStore
from .tool import RecordingToolExecutor
from .user_context import (
    InMemoryConversationHistoryStore,
    InMemoryUserMemoryStore,
    InMemoryUserPreferenceStore,
)
from .workflow_definition import (
    InMemoryWorkflowBindingStore,
    InMemoryWorkflowDefinitionStore,
)
from .workload_identity import StaticWorkloadIdentity

__all__ = [
    "InMemoryDocumentAccessProvider",
    "InMemoryDocumentArtifactStore",
    "InMemoryDocumentIndex",
    "InMemoryDocumentMetadataStore",
    "InMemoryDocumentObjectStore",
    "InMemoryBreakGlassPager",
    "InMemoryBriefingRunStore",
    "InMemoryBriefingSubscriptionStore",
    "InMemoryConversationHistoryStore",
    "InMemoryConversationSearch",
    "InMemoryConversationPolicyStore",
    "InMemoryEventBus",
    "LiveInMemoryEventBus",
    "InMemoryHilApprovalRegistry",
    "InMemoryOntologyInstanceStore",
    "InMemoryProcessRuntimeStore",
    "InMemoryRunbookRegistry",
    "InMemorySecretProvider",
    "InMemorySseSink",
    "InMemoryStateStore",
    "InMemoryUserMemoryStore",
    "InMemoryUserPreferenceStore",
    "InMemoryWorkflowBindingStore",
    "InMemoryWorkflowDefinitionStore",
    "NoOpBlastProbe",
    "RecordingDirectApiExecutor",
    "RecordingCommandRunner",
    "RecordingDocumentActivitySink",
    "RecordingRemediationPrPublisher",
    "RecordingStagePublisher",
    "RecordingToolExecutor",
    "StaticWorkloadIdentity",
    "StaticMalwareScanner",
]

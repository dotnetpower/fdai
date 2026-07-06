"""CSP-neutral cloud provider interfaces (adapters implement them).

Public API. Re-exports the five Protocols corresponding to the wire-level
contracts in ``docs/roadmap/csp-neutrality.md``. Concrete implementations
are intentionally not re-exported here - they land in later phases (W1.5
for PostgreSQL, W6.2 for in-memory fakes, W6.3 for Docker Compose backends)
and must be imported from their submodules by the composition root only.
"""

from .blast_probe import (
    BlastProbeConfigError,
    BlastProbeError,
    BlastProbeTimeoutError,
    LiveBlastProbe,
    ProbeQuery,
    ProbeResult,
    ProbeVerdict,
)
from .break_glass_pager import (
    BreakGlassDeliveryError,
    BreakGlassNoChannelError,
    BreakGlassPager,
    BreakGlassPagerError,
)
from .direct_api import (
    DirectApiError,
    DirectApiExecutor,
    DirectApiOutcome,
    DirectApiPreconditionError,
    DirectApiPromotionError,
    DirectApiReceipt,
    DirectApiRequest,
)
from .event_bus import EventBus, EventEnvelope, PublishReceipt
from .hil_registry import (
    HilApprovalDecision,
    HilApprovalRegistry,
    HilDecisionReceipt,
    HilItemAlreadyResolvedError,
    HilItemNotFoundError,
    HilPendingItem,
    HilRegistryError,
)
from .inventory import Inventory, InventoryBatch, LinkRecord, ResourceRecord
from .remediation_pr import (
    PublishReceipt as PrPublishReceipt,
)
from .remediation_pr import (
    RemediationPr,
    RemediationPrPublisher,
)
from .runbook_registry import (
    RunbookError,
    RunbookExecutionError,
    RunbookNotFoundError,
    RunbookRegistry,
    RunbookResult,
)
from .secret_provider import SecretNotFoundError, SecretProvider
from .sse import SseEvent, SseSink
from .state_store import StateStore
from .workload_identity import IdentityToken, WorkloadIdentity

__all__ = [
    "BlastProbeConfigError",
    "BlastProbeError",
    "BlastProbeTimeoutError",
    "BreakGlassDeliveryError",
    "BreakGlassNoChannelError",
    "BreakGlassPager",
    "BreakGlassPagerError",
    "DirectApiError",
    "DirectApiExecutor",
    "DirectApiOutcome",
    "DirectApiPreconditionError",
    "DirectApiPromotionError",
    "DirectApiReceipt",
    "DirectApiRequest",
    "EventBus",
    "EventEnvelope",
    "HilApprovalDecision",
    "HilApprovalRegistry",
    "HilDecisionReceipt",
    "HilItemAlreadyResolvedError",
    "HilItemNotFoundError",
    "HilPendingItem",
    "HilRegistryError",
    "IdentityToken",
    "Inventory",
    "InventoryBatch",
    "LinkRecord",
    "LiveBlastProbe",
    "PrPublishReceipt",
    "ProbeQuery",
    "ProbeResult",
    "ProbeVerdict",
    "PublishReceipt",
    "RemediationPr",
    "RemediationPrPublisher",
    "ResourceRecord",
    "RunbookError",
    "RunbookExecutionError",
    "RunbookNotFoundError",
    "RunbookRegistry",
    "RunbookResult",
    "SecretNotFoundError",
    "SecretProvider",
    "SseEvent",
    "SseSink",
    "StateStore",
    "WorkloadIdentity",
]

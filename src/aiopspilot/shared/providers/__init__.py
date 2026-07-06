"""CSP-neutral cloud provider interfaces (adapters implement them).

Public API. Re-exports the five Protocols corresponding to the wire-level
contracts in ``docs/roadmap/csp-neutrality.md``. Concrete implementations
are intentionally not re-exported here - they land in later phases (W1.5
for PostgreSQL, W6.2 for in-memory fakes, W6.3 for Docker Compose backends)
and must be imported from their submodules by the composition root only.
"""

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
from .inventory import Inventory, InventoryBatch, LinkRecord, ResourceRecord
from .remediation_pr import (
    PublishReceipt as PrPublishReceipt,
)
from .remediation_pr import (
    RemediationPr,
    RemediationPrPublisher,
)
from .secret_provider import SecretNotFoundError, SecretProvider
from .sse import SseEvent, SseSink
from .state_store import StateStore
from .workload_identity import IdentityToken, WorkloadIdentity

__all__ = [
    "DirectApiError",
    "DirectApiExecutor",
    "DirectApiOutcome",
    "DirectApiPreconditionError",
    "DirectApiPromotionError",
    "DirectApiReceipt",
    "DirectApiRequest",
    "EventBus",
    "EventEnvelope",
    "IdentityToken",
    "Inventory",
    "InventoryBatch",
    "LinkRecord",
    "PrPublishReceipt",
    "PublishReceipt",
    "RemediationPr",
    "RemediationPrPublisher",
    "ResourceRecord",
    "SecretNotFoundError",
    "SecretProvider",
    "SseEvent",
    "SseSink",
    "StateStore",
    "WorkloadIdentity",
]

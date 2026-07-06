"""In-memory fakes for the four CSP-neutrality Protocols.

Shipped in the main package (not under ``tests/``) so:

- Unit tests import them directly (no ``tests/`` -> ``src/`` reach-through).
- Debugger sessions can `from aiopspilot.shared.providers.testing import
  InMemoryEventBus` and run the loop offline.
- A future ``DevContainer`` composition root can wire these in for a "no
  Docker" run of the stack.

Nothing in this package is production-safe - mutations vanish on process
restart. The real Postgres + Kafka adapters land with W1.5 and W6.3.
"""

from .direct_api import RecordingDirectApiExecutor
from .event_bus import InMemoryEventBus
from .remediation_pr import RecordingRemediationPrPublisher
from .secret_provider import InMemorySecretProvider
from .sse import InMemorySseSink
from .state_store import InMemoryStateStore
from .workload_identity import StaticWorkloadIdentity

__all__ = [
    "InMemoryEventBus",
    "InMemorySecretProvider",
    "InMemorySseSink",
    "InMemoryStateStore",
    "RecordingDirectApiExecutor",
    "RecordingRemediationPrPublisher",
    "StaticWorkloadIdentity",
]

"""Channel-routing layer.

Implements the routing policy described in
[`docs/roadmap/interfaces/channels-and-notifications.md § 6`]
(../../../../../docs/roadmap/interfaces/channels-and-notifications.md#6-routing-policy-config-driven).

The router:

- looks up a route by ``message.category`` in the matrix,
- preserves ordered failover for A1/A3 and fans A2/A4 out to declared channels,
- refuses to dispatch to a channel whose declared
  :attr:`~fdai.shared.providers.notifications.NotificationChannel.trust_tiers`
  does not include the message's :class:`TrustTier`,
- audits every routing decision (per the safety invariants),
- escalates to the HIL sink when every configured channel fails, so a
  message is never silently dropped.

``core/`` never constructs a channel adapter - the composition root
registers them by kind + id and hands the router a
:class:`ChannelRegistry`. This module holds zero vendor knowledge.
"""

from .briefing import (
    ActionTally,
    BriefingInput,
    CostSnapshot,
    ForecastRisk,
    IncidentTally,
    StakeholderBriefing,
    StakeholderBriefingComposer,
)
from .delivery import (
    ChannelDeliveryClaim,
    ChannelDeliveryRecord,
    ChannelDeliveryState,
    DeliveryClaimStatus,
    InMemoryNotificationDeliveryStore,
    NotificationDeliveryStore,
    NotificationDispatchPlan,
)
from .matrix import (
    DeliveryMode,
    MatrixValidationError,
    NotificationMatrix,
    OnAllFailAction,
    RouteSpec,
    load_matrix_from_mapping,
    load_matrix_from_yaml,
)
from .router import (
    ChannelBinding,
    ChannelRegistry,
    NotificationRouter,
    RouteOutcome,
    RoutingResult,
)

__all__ = [
    "ActionTally",
    "BriefingInput",
    "ChannelDeliveryClaim",
    "ChannelDeliveryRecord",
    "ChannelDeliveryState",
    "ChannelBinding",
    "ChannelRegistry",
    "CostSnapshot",
    "DeliveryClaimStatus",
    "DeliveryMode",
    "ForecastRisk",
    "IncidentTally",
    "InMemoryNotificationDeliveryStore",
    "MatrixValidationError",
    "NotificationDeliveryStore",
    "NotificationDispatchPlan",
    "NotificationMatrix",
    "NotificationRouter",
    "OnAllFailAction",
    "RouteOutcome",
    "RouteSpec",
    "RoutingResult",
    "StakeholderBriefing",
    "StakeholderBriefingComposer",
    "load_matrix_from_mapping",
    "load_matrix_from_yaml",
]

"""Channel-routing layer.

Implements the routing policy described in
[`docs/roadmap/channels-and-notifications.md § 6`]
(../../../../../docs/roadmap/channels-and-notifications.md#6-routing-policy-config-driven).

The router:

- looks up a route by ``message.category`` in the matrix,
- picks channels in ``primary → fallback[0] → fallback[1] → …`` order,
- refuses to dispatch to a channel whose declared
  :attr:`~aiopspilot.shared.providers.notifications.NotificationChannel.trust_tiers`
  does not include the message's :class:`TrustTier`,
- audits every routing decision (per the safety invariants),
- escalates to the HIL sink when every configured channel fails, so a
  message is never silently dropped.

``core/`` never constructs a channel adapter — the composition root
registers them by kind + id and hands the router a
:class:`ChannelRegistry`. This module holds zero vendor knowledge.
"""

from .matrix import (
    MatrixValidationError,
    NotificationMatrix,
    OnAllFailAction,
    RouteSpec,
    load_matrix_from_mapping,
    load_matrix_from_yaml,
)
from .router import (
    ChannelRegistry,
    NotificationRouter,
    RouteOutcome,
    RoutingResult,
)

__all__ = [
    "ChannelRegistry",
    "MatrixValidationError",
    "NotificationMatrix",
    "NotificationRouter",
    "OnAllFailAction",
    "RouteOutcome",
    "RouteSpec",
    "RoutingResult",
    "load_matrix_from_mapping",
    "load_matrix_from_yaml",
]

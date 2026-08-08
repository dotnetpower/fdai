"""Independently packaged FDAI Operator Service.

Responsibility:
Expose the service factory and immutable service descriptor.

Boundary:
Accept operator HTTP traffic and publish typed requests through injected ports.

Authority and state:
Hold no managed-resource execution identity or mutable workflow state.

Dependencies:
Depend only on service-local route families and versioned contracts.

Deployment:
Run as the independently deployable, non-privileged Operator Service.
"""

from fdai_operator_service.main import SERVICE, create_app

__all__ = ["SERVICE", "create_app"]

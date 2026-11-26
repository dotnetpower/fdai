"""Provider seam for attaching authenticated raw operator_request receipts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class OperatorRequestReceiptIssuer(Protocol):
    """Attach a receipt to a raw operator_request without exposing key material."""

    def attach(self, event: Mapping[str, Any]) -> dict[str, object]:
        """Return a copy of ``event`` with an exact request-bound receipt."""
        ...


__all__ = ["OperatorRequestReceiptIssuer"]

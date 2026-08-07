"""Read-only inventory projections for Operator conversations.

Responsibility:
Own request-local inventory evidence sanitization, result projection, and
deterministic rendering.

Boundary:
Accept typed inventory queries plus authoritative provider evidence and return
bounded value projections or text. HTTP, SSE, authentication, history, query
compilation, and provider selection remain outside this package.

Authority and state:
Pure read projection with request-local values only. It cannot approve,
execute, promote, or persist inventory state and receives no executor identity.

Dependencies:
Typed inventory query contracts and bounded delivery-layer evidence helpers.

Deployment:
Runs in-process within the Operator API and creates no network boundary.
"""

from fdai.delivery.operator_api.projections.conversation.inventory.answer import (
    render_inventory_answer,
)
from fdai.delivery.operator_api.projections.conversation.inventory.projection import (
    inventory_evidence_refs,
    needs_inventory_evidence,
    partial_inventory_findings_are_grounded,
)
from fdai.delivery.operator_api.projections.conversation.inventory.rendering import (
    inventory_execution_query,
    inventory_screen_scope_unavailable_evidence,
)

__all__ = [
    "inventory_evidence_refs",
    "inventory_execution_query",
    "inventory_screen_scope_unavailable_evidence",
    "needs_inventory_evidence",
    "partial_inventory_findings_are_grounded",
    "render_inventory_answer",
]

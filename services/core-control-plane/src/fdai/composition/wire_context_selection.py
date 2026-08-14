"""Composition helper for durable context-selection shadow evaluation.

Responsibility: bind the bounded shadow runner and its durable comparison store.
Boundary: candidate policies never reach the active prompt path; this helper only
schedules off-request evaluation and appends comparisons to the tracked-state store.
"""

from __future__ import annotations

from dataclasses import replace

from fdai.composition._helpers import Container
from fdai.core.working_context import (
    ContextSelectionShadowRunner,
    ContextShadowConfig,
    StateStoreContextSelectionEvaluationStore,
)
from fdai.shared.providers.state_store import StateStore


def bind_context_selection_shadow(
    container: Container,
    *,
    state_store: StateStore,
    config: ContextShadowConfig | None = None,
) -> Container:
    """Return a new container that persists bounded shadow comparisons.

    The runner is bound to the container's current policy authority, so install every
    capability bundle first; a later
    :func:`~fdai.composition.wire_capabilities.install_capability_bundle` rebinds the
    runner to the refreshed authority and keeps this store.

    Raises :class:`ValueError` when no policy authority is bound, because a runner
    without an authority can resolve neither a baseline nor a candidate.
    """

    authority = container.context_selection_policy_authority
    if authority is None:
        raise ValueError("context-selection shadow evaluation requires a policy authority")
    store = StateStoreContextSelectionEvaluationStore(state_store)
    return replace(
        container,
        context_selection_evaluation_store=store,
        context_selection_shadow_runner=ContextSelectionShadowRunner(
            authority=authority,
            store=store,
            config=config,
        ),
    )


__all__ = ["bind_context_selection_shadow"]

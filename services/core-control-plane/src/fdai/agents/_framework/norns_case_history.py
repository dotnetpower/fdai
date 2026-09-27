"""Current-source admission for Norns operational cohorts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Protocol

from fdai.core.case_history import CaseHistoryMaterializer
from fdai.core.operational_learning import PatternCase


class NornsCaseHistoryState(Protocol):
    """Narrow Norns surface used by the case-history admission helper."""

    _case_history_materializer: CaseHistoryMaterializer | None
    _clock: Callable[[], datetime]

    def record_behavior(self, key: str) -> None: ...


async def operational_case_cohort_is_current(
    state: NornsCaseHistoryState,
    payload: Mapping[str, object],
) -> bool:
    """Reject broker replay after any exact source case becomes unavailable."""

    materializer = state._case_history_materializer
    if materializer is None:
        return True
    scope = payload.get("access_scope_digest")
    purpose = payload.get("purpose")
    raw_cases = payload.get("cases")
    if (
        not isinstance(scope, str)
        or len(scope) != 64
        or any(character not in "0123456789abcdef" for character in scope)
        or not isinstance(purpose, str)
        or not purpose.strip()
        or not isinstance(raw_cases, list)
        or not 2 <= len(raw_cases) <= 100
    ):
        state.record_behavior("operational_case_cohort_invalid_payload")
        return False
    try:
        cases = tuple(PatternCase.from_mapping(item) for item in raw_cases)
    except (TypeError, ValueError):
        state.record_behavior("operational_case_cohort_invalid_payload")
        return False
    now = state._clock()
    for case in cases:
        case_ref = f"case-history:{case.case_id}:{case.revision}:{case.manifest_digest}"
        if not await materializer.current_revision_available(
            case_ref=case_ref,
            access_scope_digest=scope,
            purpose=purpose,
            now=now,
        ):
            state.record_behavior("operational_case_cohort_source_unavailable")
            return False
    return True


__all__ = ["operational_case_cohort_is_current"]

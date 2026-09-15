"""Current-source guarded reads of Muninn's inert retained Patterns."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from fdai.core.case_history import CaseHistoryMaterializer
from fdai.core.case_history.derived import CaseHistoryProjectionStore
from fdai.core.operational_learning import OperatingPatternCompiler, PatternCase
from fdai.shared.providers.state_store import StateStore


class MuninnPatternReadMixin:
    """Read scoped Patterns without granting execution or promotion authority."""

    _durable_state_store: StateStore | None
    _case_history: CaseHistoryMaterializer | None
    _case_history_clock: Callable[[], datetime]

    if TYPE_CHECKING:

        def _case_projection_store(self, scope: str) -> CaseHistoryProjectionStore: ...

    async def read_operating_pattern(
        self, *, cohort_key: str, pattern_id: str, access_scope_digest: str, purpose: str
    ) -> dict[str, Any] | None:
        """Read an inert retained pattern only while its exact scoped cases remain current."""
        try:
            async with asyncio.timeout(5):
                return await self._read_operating_pattern(
                    cohort_key=cohort_key,
                    pattern_id=pattern_id,
                    access_scope_digest=access_scope_digest,
                    purpose=purpose,
                )
        except (TimeoutError, ValueError, TypeError):
            return None

    async def _read_operating_pattern(
        self, *, cohort_key: str, pattern_id: str, access_scope_digest: str, purpose: str
    ) -> dict[str, Any] | None:
        if self._durable_state_store is None or self._case_history is None:
            return None
        prefix = "operational-case-fingerprint-cohort:v2:"
        if not cohort_key.startswith(prefix) or len(cohort_key) != len(prefix) + 64:
            return None
        if any(
            len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
            for value in (cohort_key[len(prefix) :], pattern_id, access_scope_digest)
        ):
            return None
        if not purpose.strip() or len(purpose) > 512:
            return None
        key = f"{cohort_key}:pattern:{pattern_id}"
        record = await self._case_projection_store(access_scope_digest).read_state(key)
        if not isinstance(record, dict) or (
            record.get("schema_version") != "1.0.0"
            or set(record)
            != {
                "schema_version",
                "pattern_id",
                "access_scope_digest",
                "purpose",
                "cohort_key",
                "candidate",
                "cases",
                "execution_authority",
                "promotion_authority",
            }
            or record.get("access_scope_digest") != access_scope_digest
            or record.get("purpose") != purpose
            or record.get("pattern_id") != pattern_id
            or record.get("cohort_key") != cohort_key
            or record.get("execution_authority") is not False
            or record.get("promotion_authority") is not False
        ):
            return None
        try:
            raw_cases = record["cases"]
            if not isinstance(raw_cases, list) or not 2 <= len(raw_cases) <= 100:
                return None
            compiled = OperatingPatternCompiler().compile(
                tuple(PatternCase.from_mapping(item) for item in raw_cases),
                reviewed_at=self._case_history_clock(),
            )
            if (
                compiled is None
                or compiled.pattern_id != pattern_id
                or compiled.to_rule_candidate_mapping() != record["candidate"]
            ):
                return None
            for case_ref in compiled.immutable_case_refs:
                if not isinstance(
                    case_ref, str
                ) or not await self._case_history.current_revision_available(
                    case_ref=case_ref,
                    access_scope_digest=access_scope_digest,
                    purpose=purpose,
                    now=self._case_history_clock(),
                ):
                    return None
        except (KeyError, TypeError, ValueError):
            return None
        return record

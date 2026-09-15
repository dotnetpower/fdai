"""Principal-authorized read-only descriptions of current operating patterns."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.case_history import CaseHistoryMaterializer
from fdai.core.case_history.derived import CaseHistoryProjectionStore
from fdai.core.operational_learning import OperatingPatternCompiler, PatternCase
from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyFunctionKind,
    OntologyFunctionType,
)
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    DecisionEvidenceAdmissionProvider,
    assess_decision_evidence_admission,
)
from fdai.shared.providers.state_store import StateStore

from .functions import FunctionInvocationContext

PATTERN_QUERY = "query.operating_patterns"


class OperatingPatternQuery:
    """Map principal scope to a case scope only through exact independent read admission."""

    def __init__(
        self,
        *,
        store: StateStore,
        materializer: Callable[[], CaseHistoryMaterializer | None],
        admission: DecisionEvidenceAdmissionProvider | None,
        source_revision: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store, self._materializer, self._admission = store, materializer, admission
        self._source_revision = source_revision
        self._clock = clock or (lambda: datetime.now(UTC))

    async def read(
        self, arguments: Mapping[str, Any], context: FunctionInvocationContext
    ) -> dict[str, Any]:
        """Authorize before reading state; expose only current recompiled inert summaries."""
        async with asyncio.timeout(5):
            return await self._read(arguments, context)

    async def _read(
        self, arguments: Mapping[str, Any], context: FunctionInvocationContext
    ) -> dict[str, Any]:
        if (
            not context.principal_ref
            or not context.principal_scope_digest
            or context.purposes != ("operations-review",)
        ):
            raise PermissionError(
                "pattern query requires an authenticated operations-review principal"
            )
        if self._admission is None:
            raise PermissionError("pattern read admission is unavailable")
        if set(arguments) != {"access_scope_digest", "purpose", "failure_fingerprint", "limit"}:
            raise ValueError("pattern query fields are invalid")
        scope, purpose, limit = (
            arguments["access_scope_digest"],
            arguments["purpose"],
            arguments["limit"],
        )
        if (
            type(limit) is not int
            or not 1 <= limit <= 20
            or not isinstance(purpose, str)
            or not purpose.strip()
            or len(purpose) > 128
            or not isinstance(scope, str)
            or re.fullmatch(r"[a-f0-9]{64}", scope) is None
            or (
                arguments["failure_fingerprint"] is not None
                and (
                    not isinstance(arguments["failure_fingerprint"], str)
                    or re.fullmatch(r"[a-f0-9]{64}", arguments["failure_fingerprint"]) is None
                )
            )
        ):
            raise ValueError("pattern query limits are invalid")
        digest = content_digest(
            {"arguments": dict(arguments), "principal": context.model_dump(mode="json")}
        )
        scope_digest = content_digest(
            {
                "principal_scope": context.principal_scope_digest,
                "case_scope": scope,
                "purpose": purpose,
            }
        )
        receipt = await self._admission.admit(
            evidence_digest=digest,
            scope_digest=scope_digest,
            purpose_id="case-history-read",
            source_revision=self._source_revision,
        )
        now = self._clock()
        if (
            not isinstance(receipt, DecisionEvidenceAdmission)
            or now >= receipt.valid_until
            or assess_decision_evidence_admission(
                receipt,
                expected_evidence_digest=digest,
                expected_scope_digest=scope_digest,
                expected_purpose_id="case-history-read",
                expected_source_revision=self._source_revision,
                evaluated_at=now,
            )
        ):
            raise PermissionError("pattern query scope authorization failed")
        materializer = self._materializer()
        if materializer is None:
            return {
                "patterns": [],
                "unavailable": True,
                "truncated": False,
                "execution_authority": False,
            }
        projections = CaseHistoryProjectionStore(
            store=self._store,
            materializer=materializer,
            access_scope_digest=scope,
            clock=self._clock,
        )
        summaries = []
        final_references: set[str] = set()
        unavailable = False
        for record in await projections.pattern_records():
            if record.get("purpose") != purpose:
                continue
            if (
                set(record)
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
                or record.get("schema_version") != "1.0.0"
                or record.get("access_scope_digest") != scope
                or record.get("execution_authority") is not False
                or record.get("promotion_authority") is not False
            ):
                raise ValueError("pattern record version, scope, or authority is invalid")
            cases = tuple(PatternCase.from_mapping(item) for item in record["cases"])
            compiled = OperatingPatternCompiler().compile(cases, reviewed_at=self._clock())
            if (
                compiled is None
                or compiled.pattern_id != record["pattern_id"]
                or compiled.to_rule_candidate_mapping() != record["candidate"]
            ):
                unavailable = True
                continue
            if (
                arguments["failure_fingerprint"] is not None
                and compiled.failure_fingerprint != arguments["failure_fingerprint"]
            ):
                continue
            current = [
                await materializer.current_revision_available(
                    case_ref=ref, access_scope_digest=scope, purpose=purpose, now=self._clock()
                )
                for ref in compiled.immutable_case_refs
            ]
            if not all(value is True for value in current):
                unavailable = True
                continue
            summaries.append(
                {
                    "pattern_id": compiled.pattern_id,
                    "action_type": compiled.action_type,
                    "resource_type": compiled.resource_type,
                    "sample_size": compiled.sample_size,
                    "success_count": compiled.reusable_count,
                    "negative_count": compiled.negative_count,
                    "case_refs": list(compiled.immutable_case_refs),
                    "fdai_revision": compiled.fdai_revision,
                }
            )
            if len(summaries) > limit:
                break
            final_references.update(compiled.immutable_case_refs)
        for reference in sorted(final_references):
            if (
                await materializer.current_revision_available(
                    case_ref=reference,
                    access_scope_digest=scope,
                    purpose=purpose,
                    now=self._clock(),
                )
                is not True
            ):
                raise PermissionError("pattern source changed while reading")
        if self._clock() >= receipt.valid_until:
            raise PermissionError("pattern query authorization expired while reading")
        return {
            "patterns": summaries[:limit],
            "unavailable": unavailable,
            "truncated": len(summaries) > limit,
            "execution_authority": False,
        }


def operating_pattern_function_type() -> OntologyFunctionType:
    """Declare a bounded read function; registration grants no case access."""
    return OntologyFunctionType(
        name=PATTERN_QUERY,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest="sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["access_scope_digest", "purpose", "failure_fingerprint", "limit"],
            "properties": {
                "access_scope_digest": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "purpose": {"type": "string", "minLength": 1, "maxLength": 128},
                "failure_fingerprint": {"type": ["string", "null"], "pattern": "^[a-f0-9]{64}$"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["patterns", "unavailable", "truncated", "execution_authority"],
            "properties": {
                "patterns": {"type": "array", "maxItems": 20},
                "unavailable": {"type": "boolean"},
                "truncated": {"type": "boolean"},
                "execution_authority": {"const": False},
            },
        },
        read_sets=["Pattern"],
        required_role=CeilingRole.READER,
        purpose_bindings=["operations-review"],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        timeout_seconds=5,
        cpu_millis=1000,
        memory_bytes=134217728,
        max_output_bytes=262144,
        network_allowed=False,
        credentials_allowed=False,
    )

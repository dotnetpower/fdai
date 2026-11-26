"""Scoped configuration history reads that never expose raw retained graphs to the query DAG."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fdai_service_contracts.ontology_query import canonical_json, content_digest
from pydantic import BaseModel, ConfigDict, Field, model_validator

from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
)
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

from .functions import ContextualOntologyFunction, FunctionInvocationContext
from .query_gateway import SecuredObjectSetQueryResult
from .resource_configuration_projection import (
    GENERIC_CONFIGURATION_FIELDS,
    MODEL_CONFIGURATION_FIELDS,
    ReviewedConfiguration,
    project_resource_configuration,
)
from .topology_history import TopologyGraphAt, TopologyHistoryReader, graph_at

RESOURCE_CONFIGURATION_SNAPSHOT_FUNCTION_NAME = "query.resource_configuration_snapshot"
MAX_CONFIGURATION_RESOURCES = 16
MAX_CONFIGURATION_WINDOW_SECONDS = 31 * 24 * 60 * 60
_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"
Digest = Annotated[str, Field(pattern=_DIGEST_PATTERN)]
SnapshotReason = Literal[
    "configuration_scope_empty",
    "configuration_scope_incomplete",
    "configuration_scope_redacted",
    "configuration_resource_limit",
    "configuration_history_incomplete",
    "configuration_history_unavailable",
]


class ScopedConfigurationRecord(BaseModel):
    """One selected identity and an immutable, allowlisted projection, never provider payload."""

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")

    resource_id: str = Field(min_length=1, max_length=512)
    resource_type: str = Field(min_length=1, max_length=128)
    values_json: str = Field(min_length=2, max_length=16_384)
    projection_digest: Digest

    @model_validator(mode="after")
    def _reviewed_values_only(self) -> ScopedConfigurationRecord:
        values = json.loads(self.values_json)
        if not isinstance(values, dict) or canonical_json(values) != self.values_json:
            raise ValueError("configuration projection MUST be canonical object JSON")
        if self.projection_digest != content_digest(values):
            raise ValueError("configuration projection digest does not match reviewed fields")
        if self.resource_type == "llm-model-deployment":
            record = OntologyObjectRecord(
                id=self.resource_id,
                object_type="Resource",
                properties={"type": self.resource_type, "properties": values},
            )
            reviewed = project_resource_configuration(record)
            if set(values) != set(MODEL_CONFIGURATION_FIELDS) or reviewed.values != values:
                raise ValueError("model configuration contains unreviewed or invalid fields")
        elif set(values) != set(GENERIC_CONFIGURATION_FIELDS) or any(
            value is not None
            and (
                not isinstance(value, dict)
                or set(value) != {"digest"}
                or not isinstance(value["digest"], str)
                or re.fullmatch(_DIGEST_PATTERN, value["digest"]) is None
            )
            for value in values.values()
        ):
            raise ValueError("generic configuration permits only reviewed field digests")
        return self

    @property
    def projection(self) -> ReviewedConfiguration:
        """Return a fresh reviewed value map for the pure comparison reducer."""
        values = json.loads(self.values_json)
        return ReviewedConfiguration(
            values=values,
            missing_fields=tuple(sorted(key for key, value in values.items() if value is None)),
            digest=self.projection_digest,
        )


class ScopedConfigurationSnapshot(BaseModel):
    """Time- and receipt-bound selected facts, with opaque provenance and no global references."""

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")

    scope_receipt_digest: Digest
    as_of: datetime
    known_at: datetime
    records: tuple[ScopedConfigurationRecord, ...] = Field(max_length=MAX_CONFIGURATION_RESOURCES)
    complete: bool
    reason: SnapshotReason | None
    provenance_digest: Digest | None
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _bounded_snapshot(self) -> ScopedConfigurationSnapshot:
        verify_snapshot_times(self.as_of, self.known_at)
        if self.complete != (self.reason is None):
            raise ValueError("configuration snapshot completeness is inconsistent")
        if self.complete and self.provenance_digest is None:
            raise ValueError("complete configuration snapshot requires provenance")
        if not self.complete and (self.records or self.provenance_digest is not None):
            raise ValueError("incomplete configuration snapshot MUST NOT disclose historical facts")
        ids = tuple(record.resource_id for record in self.records)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("configuration snapshot identities MUST be unique and sorted")
        return self

    @property
    def digest(self) -> str:
        """Content-address the complete scoped DTO without any hidden history data."""
        return content_digest(self.model_dump(mode="json"))


def resource_configuration_snapshot_function_type() -> OntologyFunctionType:
    """Declare the scoped, read-only retained-history source using existing query dependencies."""
    projection = Path(__file__).with_name("resource_configuration_projection.py")
    return OntologyFunctionType(
        name=RESOURCE_CONFIGURATION_SNAPSHOT_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest="sha256:"
        + hashlib.sha256(Path(__file__).read_bytes() + projection.read_bytes()).hexdigest(),
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["query_result", "as_of", "known_at"],
            "properties": {
                "query_result": {"type": "object", "x-fdai-dependency-only": True},
                "as_of": {"type": "string", "format": "date-time"},
                "known_at": {"type": "string", "format": "date-time"},
            },
        },
        output_schema=ScopedConfigurationSnapshot.model_json_schema(),
        read_sets=["Resource"],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=["operations-review"],
        timeout_seconds=10,
        cpu_millis=500,
        memory_bytes=67_108_864,
        max_output_bytes=1_048_576,
        network_allowed=False,
        credentials_allowed=False,
    )


def resource_configuration_snapshot_function(
    ontology_release: OntologyRelease,
    *,
    reader: TopologyHistoryReader,
) -> ContextualOntologyFunction:
    """Admit an issued scope before history reads and return only its reviewed facts."""
    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        RESOURCE_CONFIGURATION_SNAPSHOT_FUNCTION_NAME,
    )

    async def evaluate(arguments: Mapping[str, Any], context: FunctionInvocationContext) -> object:
        as_of = configuration_timestamp(arguments["as_of"])
        known_at = configuration_timestamp(arguments["known_at"])
        verify_snapshot_times(as_of, known_at)
        secured = authorized_configuration_scope(
            arguments["query_result"],
            context,
            ontology_release,
            known_at=known_at,
        )
        reason = configuration_scope_reason(secured)
        if reason is not None:
            return _unavailable(secured, as_of, known_at, reason)
        try:
            batches = await reader.read(as_of=as_of, known_at=known_at)
            view = graph_at(batches, as_of=as_of, known_at=known_at)
        except (TypeError, ValueError):
            return _unavailable(secured, as_of, known_at, "configuration_history_incomplete")
        except Exception:
            # Reader error messages can contain unselected source identities or provider payloads.
            return _unavailable(secured, as_of, known_at, "configuration_history_unavailable")
        return project_configuration_snapshot(query_result=secured, view=view)

    return evaluate


def project_configuration_snapshot(
    *,
    query_result: SecuredObjectSetQueryResult,
    view: TopologyGraphAt,
) -> ScopedConfigurationSnapshot:
    """Project an internally retained graph; this pure helper never returns raw history data."""
    verify_snapshot_times(view.as_of, view.known_at)
    reason = configuration_scope_reason(query_result)
    if reason is not None:
        return _unavailable(query_result, view.as_of, view.known_at, reason)
    if not (
        view.complete
        and view.graph.source_complete
        and not view.graph.truncated
        and view.ontology_release_digests == (query_result.receipt.ontology_release.digest,)
        and view.source_receipt_digests
        and view.revision_ids
    ):
        return _unavailable(
            query_result,
            view.as_of,
            view.known_at,
            "configuration_history_incomplete",
        )
    selected = {item.id: item for item in query_result.materialization.graph.objects}
    records: dict[str, ScopedConfigurationRecord] = {}
    for record in view.graph.objects:
        target = selected.get(record.id)
        if target is None:
            continue
        resource_type = target.properties.get("type")
        if (
            record.object_type != "Resource"
            or not isinstance(resource_type, str)
            or not resource_type.strip()
            or record.properties.get("type") != resource_type
        ):
            continue
        if record.id in records:
            raise ValueError("configuration history contains duplicate selected identities")
        reviewed = project_resource_configuration(record)
        records[record.id] = ScopedConfigurationRecord(
            resource_id=record.id,
            resource_type=resource_type,
            values_json=canonical_json(dict(reviewed.values)),
            projection_digest=reviewed.digest,
        )
    scoped_records = tuple(records[key] for key in sorted(records))
    scope_digest = configuration_scope_digest(query_result)
    return ScopedConfigurationSnapshot(
        scope_receipt_digest=scope_digest,
        as_of=view.as_of,
        known_at=view.known_at,
        records=scoped_records,
        complete=True,
        reason=None,
        provenance_digest=content_digest(
            {
                "scope_receipt_digest": scope_digest,
                "as_of": view.as_of.isoformat(),
                "known_at": view.known_at.isoformat(),
                "source_receipt_digests": view.source_receipt_digests,
                "reviewed_records": [record.model_dump(mode="json") for record in scoped_records],
            }
        ),
    )


def authorized_configuration_scope(
    value: object,
    context: FunctionInvocationContext,
    release: OntologyRelease,
    *,
    known_at: datetime,
) -> SecuredObjectSetQueryResult:
    """Require the FunctionNodeHandler marker for an issued receipt."""
    secured = SecuredObjectSetQueryResult.model_validate(value)
    if (
        context.purposes != ("operations-review",)
        or secured.receipt.purpose != "operations-review"
        or secured.receipt.caller_role != context.caller_role
        or secured.receipt.ontology_release != release.ref()
        or secured.receipt.projected_result_digest not in context.evidence_refs
    ):
        raise PermissionError("configuration read requires an issued current authorized scope")
    if abs((secured.receipt.observation_cutoff - known_at).total_seconds()) > 5:
        raise ValueError("configuration scope is not current at the requested knowledge cutoff")
    return secured


def configuration_scope_reason(secured: SecuredObjectSetQueryResult) -> SnapshotReason | None:
    """Reject partial, redacted, or oversized selections before historical reads or disclosures."""
    graph = secured.materialization.graph
    if not secured.receipt.complete or graph.truncated:
        return "configuration_scope_incomplete"
    if any(secured.receipt.redactions.model_dump().values()):
        return "configuration_scope_redacted"
    if not graph.objects:
        return "configuration_scope_empty"
    if len(graph.objects) > MAX_CONFIGURATION_RESOURCES:
        return "configuration_resource_limit"
    if any(record.object_type != "Resource" for record in graph.objects) or len(
        {record.id for record in graph.objects}
    ) != len(graph.objects):
        raise ValueError("configuration scope MUST contain unique Resource identities")
    return None


def configuration_scope_digest(secured: SecuredObjectSetQueryResult) -> str:
    """Bind snapshot reuse to the issued receipt's principal, purpose, and release."""
    return content_digest(secured.receipt.model_dump(mode="json"))


def configuration_timestamp(value: object) -> datetime:
    """Parse one explicit aware RFC 3339 query boundary."""
    if not isinstance(value, str):
        raise ValueError("configuration time MUST be an RFC 3339 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("configuration time MUST be a valid RFC 3339 timestamp") from None
    if parsed.tzinfo is None:
        raise ValueError("configuration time MUST be timezone-aware")
    return parsed.astimezone(UTC)


def verify_snapshot_times(as_of: datetime, known_at: datetime) -> None:
    """Bound history to the knowledge cutoff and retained comparison window."""
    if as_of.tzinfo is None or known_at.tzinfo is None:
        raise ValueError("configuration times MUST be timezone-aware")
    if not 0 <= (known_at - as_of).total_seconds() <= MAX_CONFIGURATION_WINDOW_SECONDS:
        raise ValueError("configuration history requires a bounded past observation")


def _unavailable(
    secured: SecuredObjectSetQueryResult,
    as_of: datetime,
    known_at: datetime,
    reason: SnapshotReason,
) -> ScopedConfigurationSnapshot:
    return ScopedConfigurationSnapshot(
        scope_receipt_digest=configuration_scope_digest(secured),
        as_of=as_of,
        known_at=known_at,
        records=(),
        complete=False,
        reason=reason,
        provenance_digest=None,
    )

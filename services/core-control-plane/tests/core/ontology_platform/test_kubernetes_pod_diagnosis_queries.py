"""Exact-release Kubernetes Pod diagnosis FunctionType tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.kubernetes_pod_diagnosis_evidence import (
    KubernetesPodLogEvidence,
)
from fdai.core.ontology_platform.kubernetes_pod_diagnosis_queries import (
    kubernetes_pod_diagnosis_function,
    kubernetes_pod_diagnosis_function_type,
)
from fdai.core.ontology_platform.models import (
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetMaterialization,
)
from fdai.core.ontology_platform.query_gateway import (
    ObjectSetRedactionSummary,
    SecuredObjectSetQueryReceipt,
    SecuredObjectSetQueryResult,
    _projected_result_digest,
)
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyObjectRecord,
)
from fdai.shared.providers.state_evidence import (
    STATE_FACT_METADATA_PROPERTY,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

_CUTOFF = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)
_POD_ID = "cluster:example/kubernetes/pod/example"


def _state_fact_metadata(**overrides: object) -> StateFactMetadata:
    values: dict[str, object] = {
        "lane": StateFactLane.OBSERVED,
        "authority": StateFactAuthority.PROVIDER,
        "source_identity": "kubernetes-api-inventory",
        "source_revision": "generation-1",
        "effective_at": _CUTOFF,
        "recorded_at": _CUTOFF,
        "evidence_cutoff": _CUTOFF,
        "freshness_ceiling_seconds": 300,
        "completeness": 1.0,
        "synthetic": False,
        "evidence_refs": ("kubernetes:pod:example",),
    }
    values.update(overrides)
    return StateFactMetadata(**values)  # type: ignore[arg-type]


class _LogReader:
    def __init__(self, *, complete: bool = True) -> None:
        self.complete = complete
        self.calls: list[tuple[str, datetime, datetime]] = []

    async def collect(
        self,
        *,
        pod_uid: str,
        start: datetime,
        end: datetime,
    ) -> KubernetesPodLogEvidence:
        self.calls.append((pod_uid, start, end))
        return KubernetesPodLogEvidence(
            pod_uid=pod_uid,
            start=start,
            end=end,
            source_identity="azure-monitor",
            complete=self.complete,
            limitation=None if self.complete else "source_unavailable",
            total_records=1 if self.complete else 0,
            error_records=1 if self.complete else 0,
            first_recorded_at=end - timedelta(minutes=2) if self.complete else None,
            last_recorded_at=end - timedelta(minutes=2) if self.complete else None,
            record_digests=(("sha256:" + ("a" * 64)),) if self.complete else (),
            evidence_refs=("pod-log-source:azure-monitor",),
        )


_UNSET: object = object()


def _secured(
    *,
    objects: tuple[OntologyObjectRecord, ...] | None = None,
    state_fact_metadata: StateFactMetadata | None | object = _UNSET,
    container_terminations: list[dict[str, object]] | None = None,
) -> SecuredObjectSetQueryResult:
    resolved_metadata = (
        _state_fact_metadata() if state_fact_metadata is _UNSET else state_fact_metadata
    )
    pod = OntologyObjectRecord(
        id=_POD_ID,
        object_type="Resource",
        properties={
            "id": _POD_ID,
            "type": "kubernetes.pod",
            "properties": {
                "uid": "pod-uid-a",
                "container_terminations": (
                    container_terminations
                    if container_terminations is not None
                    else [
                        {
                            "container_name": "api",
                            "observation_kind": "previous",
                            "reason": "OOMKilled",
                            "exit_code": 137,
                            "signal": 9,
                            "finished_at": (_CUTOFF - timedelta(minutes=5)).isoformat(),
                        }
                    ]
                ),
                **(
                    {STATE_FACT_METADATA_PROPERTY: resolved_metadata.to_mapping()}
                    if resolved_metadata is not None
                    else {}
                ),
            },
        },
    )
    selected = objects if objects is not None else (pod,)
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=_CUTOFF,
        purpose="operations-review",
        limit=2,
    )
    materialization = ObjectSetMaterialization(
        definition=definition,
        graph=OntologyGraphSnapshot(objects=selected, links=(), truncated=False),
        concrete_types=("Resource",),
        truncated=False,
    )
    release = build_ontology_release(function_types=(kubernetes_pod_diagnosis_function_type(),))
    receipt = SecuredObjectSetQueryReceipt(
        ontology_release=release.ref(),
        projected_result_digest=_projected_result_digest(materialization),
        purpose="operations-review",
        caller_role="reader",
        observation_cutoff=_CUTOFF,
        as_of_skew_seconds=0,
        returned_object_count=len(selected),
        returned_link_count=0,
        complete=True,
        truncated=False,
        redactions=ObjectSetRedactionSummary(
            objects_with_redactions=0,
            redacted_identity_count=0,
            access_scope_count=0,
            purpose_binding_count=0,
            undeclared_property_count=0,
            links_with_redactions=0,
            redacted_link_property_count=0,
            removed_link_count=0,
        ),
    )
    return SecuredObjectSetQueryResult(materialization=materialization, receipt=receipt)


def _events(
    *,
    complete: bool = True,
    object_uid: str | None = "pod-uid-a",
    event_kind: str = "Killing",
) -> dict[str, object]:
    return {
        "rows": [
            {
                "row_id": "event-1",
                "values": {
                    "event_kind": event_kind,
                    "evidence_ref": "kubernetes-event:event-1",
                    **({"object_uid": object_uid} if object_uid is not None else {}),
                },
            }
        ],
        "complete": complete,
        "truncation_reason": None if complete else "source_retention_unverified",
    }


async def test_function_queries_exact_uid_and_returns_content_free_diagnosis() -> None:
    declaration = kubernetes_pod_diagnosis_function_type()
    release = build_ontology_release(function_types=(declaration,))
    reader = _LogReader()
    function = kubernetes_pod_diagnosis_function(release, log_reader=reader)

    result = await function(
        {
            "pod_query_result": _secured().model_dump(mode="json"),
            "lifecycle_events": _events(),
            "lookback_seconds": 900,
        },
        FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )

    assert reader.calls == [("pod-uid-a", _CUTOFF - timedelta(minutes=15), _CUTOFF)]
    assert result["complete"] is True
    values = result["rows"][0]["values"]
    assert values["status"] == "oom_killed"
    assert values["cause_claim_supported"] is False
    assert values["execution_authority"] is False
    assert "body" not in values


async def test_function_holds_before_provider_io_without_one_exact_pod() -> None:
    declaration = kubernetes_pod_diagnosis_function_type()
    release = build_ontology_release(function_types=(declaration,))
    reader = _LogReader()
    function = kubernetes_pod_diagnosis_function(release, log_reader=reader)

    result = await function(
        {
            "pod_query_result": _secured(objects=()).model_dump(mode="json"),
            "lifecycle_events": _events(),
            "lookback_seconds": 900,
        },
        FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )

    assert result["complete"] is False
    assert result["truncation_reason"] == "pod_target_not_exact"
    assert reader.calls == []


async def test_function_preserves_incomplete_lifecycle_event_coverage() -> None:
    declaration = kubernetes_pod_diagnosis_function_type()
    release = build_ontology_release(function_types=(declaration,))
    function = kubernetes_pod_diagnosis_function(release, log_reader=_LogReader())

    result = await function(
        {
            "pod_query_result": _secured().model_dump(mode="json"),
            "lifecycle_events": _events(complete=False),
            "lookback_seconds": 900,
        },
        FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )

    assert result["complete"] is False
    assert "lifecycle_events_source_retention_unverified" in result["truncation_reason"]


async def test_function_excludes_foreign_pod_lifecycle_events() -> None:
    """Lifecycle rows for another Pod MUST NOT shape this Pod's diagnosis."""

    declaration = kubernetes_pod_diagnosis_function_type()
    release = build_ontology_release(function_types=(declaration,))
    reader = _LogReader()
    function = kubernetes_pod_diagnosis_function(release, log_reader=reader)

    result = await function(
        {
            "pod_query_result": _secured(
                container_terminations=[
                    {
                        "container_name": "api",
                        "observation_kind": "previous",
                        "reason": "Error",
                        "exit_code": 1,
                        "finished_at": (_CUTOFF - timedelta(minutes=5)).isoformat(),
                    }
                ],
            ).model_dump(mode="json"),
            "lifecycle_events": _events(object_uid="pod-uid-other", event_kind="Unhealthy"),
            "lookback_seconds": 900,
        },
        FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )

    assert result["complete"] is True
    values = result["rows"][0]["values"]
    # "Unhealthy" only classifies as probe failure when it comes from this exact
    # Pod's own lifecycle reasons; the foreign "Killing" row MUST NOT count.
    assert values["status"] == "abnormal_exit"


async def test_function_termination_outside_lookback_window_is_not_reported() -> None:
    """A termination older than the requested lookback MUST NOT answer this window."""

    declaration = kubernetes_pod_diagnosis_function_type()
    release = build_ontology_release(function_types=(declaration,))
    reader = _LogReader()
    function = kubernetes_pod_diagnosis_function(release, log_reader=reader)

    result = await function(
        {
            "pod_query_result": _secured(
                container_terminations=[
                    {
                        "container_name": "api",
                        "observation_kind": "previous",
                        "reason": "OOMKilled",
                        "exit_code": 137,
                        "signal": 9,
                        "finished_at": (_CUTOFF - timedelta(hours=2)).isoformat(),
                    }
                ],
            ).model_dump(mode="json"),
            "lifecycle_events": _events(),
            "lookback_seconds": 900,
        },
        FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )

    values = result["rows"][0]["values"]
    assert values["status"] == "insufficient_evidence"
    assert values["termination_reason"] is None
    assert "termination_unavailable" in values["evidence_gaps"]


async def test_function_holds_before_provider_io_without_pod_state_evidence() -> None:
    """A Pod without a retained state fact MUST hold before any log read."""

    declaration = kubernetes_pod_diagnosis_function_type()
    release = build_ontology_release(function_types=(declaration,))
    reader = _LogReader()
    function = kubernetes_pod_diagnosis_function(release, log_reader=reader)

    result = await function(
        {
            "pod_query_result": _secured(state_fact_metadata=None).model_dump(mode="json"),
            "lifecycle_events": _events(),
            "lookback_seconds": 900,
        },
        FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )

    assert result["complete"] is False
    assert result["truncation_reason"] == "pod_state_evidence_unavailable"
    assert reader.calls == []


async def test_function_holds_before_provider_io_on_stale_pod_state_evidence() -> None:
    """A Pod state fact older than its freshness ceiling MUST hold before any log read."""

    declaration = kubernetes_pod_diagnosis_function_type()
    release = build_ontology_release(function_types=(declaration,))
    reader = _LogReader()
    function = kubernetes_pod_diagnosis_function(release, log_reader=reader)
    stale_metadata = _state_fact_metadata(
        effective_at=_CUTOFF - timedelta(minutes=20),
        recorded_at=_CUTOFF - timedelta(minutes=20),
        evidence_cutoff=_CUTOFF - timedelta(minutes=20),
        freshness_ceiling_seconds=300,
    )

    result = await function(
        {
            "pod_query_result": _secured(
                state_fact_metadata=stale_metadata,
            ).model_dump(mode="json"),
            "lifecycle_events": _events(),
            "lookback_seconds": 900,
        },
        FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )

    assert result["complete"] is False
    assert result["truncation_reason"] == "pod_state_evidence_stale"
    assert reader.calls == []


async def test_function_holds_before_provider_io_on_conflicting_pod_state_evidence() -> None:
    """A Pod state fact with a recorded conflict MUST hold before any log read."""

    declaration = kubernetes_pod_diagnosis_function_type()
    release = build_ontology_release(function_types=(declaration,))
    reader = _LogReader()
    function = kubernetes_pod_diagnosis_function(release, log_reader=reader)
    conflicting_metadata = _state_fact_metadata(conflicts=("dual_source_mismatch",))

    result = await function(
        {
            "pod_query_result": _secured(
                state_fact_metadata=conflicting_metadata,
            ).model_dump(mode="json"),
            "lifecycle_events": _events(),
            "lookback_seconds": 900,
        },
        FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )

    assert result["complete"] is False
    assert result["truncation_reason"] == "pod_state_evidence_conflict:dual_source_mismatch"
    assert reader.calls == []

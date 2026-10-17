"""Validate a complete tuple exclusively against rows held by a local database lease."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any

from fdai_service_contracts.ontology_query import content_digest
from jsonschema import Draft202012Validator
from referencing import Registry

from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.operational_learning.patterns import (
    _DEFAULT_MAX_CASE_AGE,
    OperatingPatternCompiler,
    PatternCase,
)
from fdai.core.tiers.t1_lightweight.contextual_reuse import (
    contextual_reuse_reasons,
    current_reuse_evidence_digest,
)
from fdai.core.tiers.t1_lightweight.retained_pattern_bindings import (
    RetainedPatternQualification,
    RetainedReuseStatistics,
)
from fdai.core.tiers.t1_lightweight.retained_pattern_lease import RetainedPatternLeaseEvidence
from fdai.core.tiers.t1_lightweight.tier import (
    LearnedAction,
    OperationalCaseContext,
    SimilarityMatch,
)
from fdai.shared.contracts.models import Event, OntologyActionType
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    assess_decision_evidence_admission,
)

from .local_pattern_owner import owner_key, parse_verification
from .state_store_case_history import _from_mapping
from .state_store_decision_evidence import (
    decision_evidence_state_key,
    parse_decision_evidence_record,
)


def lookups(value: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    read = value["read"]
    args, principal = read["arguments"], read["principal"]
    return (
        {
            "evidence_digest": content_digest({"arguments": args, "principal": principal}),
            "scope_digest": content_digest(
                {
                    "principal_scope": principal["principal_scope_digest"],
                    "case_scope": args["access_scope_digest"],
                    "purpose": args["purpose"],
                }
            ),
            "purpose_id": "case-history-read",
            "source_revision": read["source_revision"],
        },
        {
            "evidence_digest": value["reuse"]["evidence_digest"],
            "scope_digest": value["reuse"]["scope_digest"],
            "purpose_id": "current-case-reuse",
            "source_revision": value["match"]["context"]["graph_digest"],
        },
    )


def base_keys(value: Mapping[str, Any]) -> tuple[str, ...]:
    args, principal, match = (
        value["read"]["arguments"],
        value["read"]["principal"],
        value["match"],
    )
    scope, context = args["access_scope_digest"], match["context"]
    return (
        "case-history-derived:v1:" + scope,
        *(f"case-history:latest:{case['case_id']}" for case in value["cohort"]["cases"]),
        owner_key("principal", principal["principal_ref"], scope, args["purpose"]),
        owner_key("statistics", match["signature"], context["case_ref"], scope),
        owner_key("reuse", value["event"]["event_id"], context["case_ref"], match["signature"]),
        owner_key("action", match["action_type"]),
        *(decision_evidence_state_key(**lookup) for lookup in lookups(value)),
    )


def artifact_key(storage_ref: str) -> str:
    return "catalog-review-case-artifact:" + hashlib.sha256(storage_ref.encode()).hexdigest()


def validate_locked(
    request: RetainedPatternQualification, rows: Mapping[str, Mapping[str, Any]], *, now: datetime
) -> RetainedPatternLeaseEvidence | None:
    value = request.descriptor
    args, principal, match = (
        value["read"]["arguments"],
        value["read"]["principal"],
        value["match"],
    )
    scope, purpose = args["access_scope_digest"], args["purpose"]
    invocation = FunctionInvocationContext.model_validate(principal)
    if (
        not invocation.principal_ref
        or not invocation.principal_scope_digest
        or not invocation.authentication_receipt_ref
        or not invocation.authentication_request_ref
        or invocation.purposes != ("operations-review",)
    ):
        return None
    context = OperationalCaseContext.from_mapping(match["context"])
    event = Event.model_validate(value["event"])
    action = LearnedAction(
        signature=match["signature"],
        rule_id=match["rule_id"],
        action_type=match["action_type"],
        params=match["params"],
        incident_id=match["incident_id"],
        success_rate=match["success_rate"],
        reuse_count=match["reuse_count"],
        operational_case=context,
    )
    projected = rows["case-history-derived:v1:" + scope]
    if not any(entry["value"] == value["cohort"] for entry in projected["entries"].values()):
        return None
    cases = tuple(PatternCase.from_mapping(raw) for raw in value["cohort"]["cases"])
    compiled = OperatingPatternCompiler().compile(cases, reviewed_at=now)
    if (
        compiled is None
        or compiled.reusable_count < 2
        or value["cohort"]["access_scope_digest"] != scope
        or value["cohort"]["purpose"] != purpose
        or context.access_scope_digest != scope
        or context.purpose != purpose
        or compiled.pattern_id != value["cohort"]["pattern_id"]
        or compiled.to_rule_candidate_mapping() != value["cohort"]["candidate"]
        or compiled.action_type != action.action_type
        or compiled.action_type != context.action_type
        or compiled.resource_type != context.resource_type
        or compiled.failure_fingerprint != context.failure_fingerprint
        or action.incident_id != context.case_ref.split(":")[1]
        or not any(
            case.reusable
            and case.immutable_case_ref == context.case_ref
            and case.event_time_cutoff == context.evidence_cutoff
            for case in cases
        )
        or value["cohort"]["execution_authority"] is not False
        or value["cohort"]["promotion_authority"] is not False
    ):
        return None
    source_expiries: list[datetime] = []
    for case in cases:
        record = _from_mapping(rows["case-history:latest:" + case.case_id])
        if (
            record.case_id != case.case_id
            or record.revision != case.revision
            or record.manifest_digest != case.manifest_digest
            or record.access_scope_digest != scope
            or record.purpose != purpose
            or record.storage_ref is None
            or record.deleted_at is not None
            or record.deletion_started_at is not None
            or not record.sealed_at <= now < record.deletion_due_at
        ):
            return None
        artifact = rows[artifact_key(record.storage_ref)]
        encoded = artifact["content_base64"]
        if not isinstance(encoded, str) or len(encoded) > 1_398_104:
            return None
        content = base64.b64decode(encoded, validate=True)
        if (
            hashlib.sha256(content).hexdigest() != record.manifest_digest
            or artifact["content_digest"] != record.manifest_digest
            or artifact["storage_ref_digest"]
            != hashlib.sha256(record.storage_ref.encode()).hexdigest()
            or len(content) != record.artifact_size
        ):
            return None
        source_expiries.extend(
            (record.deletion_due_at, case.event_time_cutoff + _DEFAULT_MAX_CASE_AGE)
        )
    grant = rows[owner_key("principal", principal["principal_ref"], scope, purpose)]
    if (
        grant.get("allowed") is not True
        or grant["context"] != principal
        or grant["scope"] != scope
        or grant["purpose"] != purpose
        or now >= datetime.fromisoformat(grant["valid_until"])
    ):
        return None
    measured = rows[owner_key("statistics", action.signature, context.case_ref, scope)]
    if measured.get("authorized") is not True or measured["statistics"] != value["measurement"]:
        return None
    statistics = dict(measured["statistics"])
    for key in ("observed_at", "valid_until"):
        statistics[key] = datetime.fromisoformat(statistics[key])
    current = RetainedReuseStatistics(**statistics)
    if not current.matches(SimilarityMatch(action, match["score"]), now=now):
        return None
    registered = OntologyActionType.model_validate(rows[owner_key("action", action.action_type)])
    if (
        registered.name != action.action_type
        or registered.argument_schema is None
        or not Draft202012Validator(registered.argument_schema, registry=Registry()).is_valid(
            dict(action.params)
        )
    ):
        return None
    admissions: list[DecisionEvidenceAdmission] = []
    for lookup in lookups(value):
        admission = parse_decision_evidence_record(
            rows[decision_evidence_state_key(**lookup)]
        ).admission
        if now >= admission.valid_until or assess_decision_evidence_admission(
            admission,
            expected_evidence_digest=lookup["evidence_digest"],
            expected_scope_digest=lookup["scope_digest"],
            expected_purpose_id=lookup["purpose_id"],
            expected_source_revision=lookup["source_revision"],
            evaluated_at=now,
        ):
            return None
        admissions.append(admission)
    reuse = rows[owner_key("reuse", str(event.event_id), context.case_ref, action.signature)]
    observed = parse_verification(dict(reuse["verification"]))
    if (
        reuse["scope_digest"] != value["reuse"]["scope_digest"]
        or current_reuse_evidence_digest(observed) != value["reuse"]["evidence_digest"]
        or admissions[1].to_mapping() != value["reuse"]["admission"]
        or contextual_reuse_reasons(
            event=event,
            action=action,
            context=context,
            verification=replace(observed, decision_evidence=admissions[1]),
            evaluated_at=now,
        )
    ):
        return None
    return RetainedPatternLeaseEvidence(
        tuple_digest=request.evidence_digest,
        scope_digest=request.scope_digest,
        dependencies_digest=content_digest(
            {content_digest(key): content_digest(row) for key, row in rows.items()}
        ),
        valid_until=min(
            current.valid_until,
            *(admission.valid_until for admission in admissions),
            datetime.fromisoformat(grant["valid_until"]),
            *source_expiries,
        ),
        read_admission=admissions[0],
        reuse_admission=admissions[1],
    )

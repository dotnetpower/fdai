"""Decode durable IAM access and assignment proposals into bounded projections."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from fdai_operator_service.families.iam.errors import IamUnavailableError


def access_request_from_proposal(value: Mapping[str, object]) -> dict[str, object]:
    """Decode one durable access request without exposing untyped payload fields."""
    payload = value.get("payload")
    if not isinstance(payload, Mapping):
        raise IamUnavailableError("stored access-request proposal payload is malformed")
    principal = payload.get("principal")
    if not isinstance(principal, Mapping):
        raise IamUnavailableError("stored access-request principal is malformed")
    proposal_id = value.get("proposal_id")
    accepted_at = value.get("accepted_at")
    required = {
        "idempotency_key": payload.get("idempotency_key"),
        "identity_provider": payload.get("identity_provider"),
        "target_subject_id": payload.get("target_subject_id"),
        "target_username": payload.get("target_username"),
        "operation": payload.get("operation"),
        "role": payload.get("role"),
        "justification": payload.get("justification"),
    }
    if (
        not isinstance(proposal_id, str)
        or not isinstance(accepted_at, str)
        or not isinstance(principal.get("oid"), str)
        or any(not isinstance(item, str) or not item for item in required.values())
    ):
        raise IamUnavailableError("stored access-request proposal is malformed")
    return {
        "request_id": proposal_id,
        **required,
        "requester_oid": principal["oid"],
        "requested_at": accepted_at,
        "status": "pending",
        "reviewed_by": None,
        "reviewed_at": None,
        "review_justification": None,
        "proposal_id": proposal_id,
        "dispatch_status": value.get("dispatch_status", "pending"),
    }


def assignment_case_from_proposal(value: Mapping[str, object]) -> dict[str, object]:
    """Decode one durable assignment proposal and reject malformed nested collections."""
    payload = value.get("payload")
    proposal_id = value.get("proposal_id")
    if not isinstance(payload, Mapping) or not isinstance(proposal_id, str):
        raise IamUnavailableError("stored assignment proposal is malformed")
    principal = payload.get("principal")
    subject_provider = payload.get("subject_provider")
    subject_id = payload.get("subject_id")
    if not isinstance(principal, Mapping):
        raise IamUnavailableError("stored assignment identity is malformed")
    requester = principal.get("oid")
    requested_role = payload.get("requested_role")
    idempotency_key = payload.get("idempotency_key")
    justification = payload.get("justification")
    duty_bindings = payload.get("duty_bindings")
    goal_refs = payload.get("goal_refs")
    if (
        not all(
            isinstance(item, str) and item
            for item in (
                requester,
                subject_provider,
                subject_id,
                requested_role,
                idempotency_key,
                justification,
            )
        )
        or not isinstance(duty_bindings, list)
        or any(not isinstance(item, Mapping) for item in duty_bindings)
        or not isinstance(goal_refs, list)
        or any(not isinstance(item, str) or not item for item in goal_refs)
    ):
        raise IamUnavailableError("stored assignment proposal fields are malformed")
    return {
        "case_id": proposal_id,
        "intent": {
            "idempotency_key": idempotency_key,
            "subject": {"provider": subject_provider, "subject_id": subject_id},
            "requested_role": requested_role,
            "duty_bindings": [dict(item) for item in duty_bindings],
            "goal_refs": list(goal_refs),
            "requester_ref": requester,
            "justification": justification,
            **(
                {"revocation": payload["revocation"]}
                if payload.get("revocation") is not None
                else {}
            ),
        },
        "state": "draft",
        "revision": 1,
        "reviews": [],
        "effect_receipts": [],
        "degraded_reason": None,
        "superseded_by": None,
    }


def project_assignment_case(
    assignment: Mapping[str, object],
    *,
    submitted: Mapping[str, object] | None,
    reviews: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Project ordered assignment reviews into one deterministic case state."""
    projected = dict(assignment)
    if submitted is None:
        return projected
    projected["state"] = "pending_review"
    projected["revision"] = 2
    projected_reviews: list[dict[str, object]] = []
    rejected = False
    for review in sorted(reviews, key=lambda item: str(item.get("accepted_at") or "")):
        payload = review.get("payload")
        principal = payload.get("principal") if isinstance(payload, Mapping) else None
        reviewer = principal.get("oid") if isinstance(principal, Mapping) else None
        decision = payload.get("decision") if isinstance(payload, Mapping) else None
        accepted_at = review.get("accepted_at")
        if (
            not isinstance(reviewer, str)
            or decision not in {"approve", "reject"}
            or not isinstance(accepted_at, str)
        ):
            raise IamUnavailableError("stored assignment review is malformed")
        projected_reviews.append(
            {"reviewer_ref": reviewer, "decision": decision, "reviewed_at": accepted_at}
        )
        rejected = rejected or decision == "reject"
    projected["reviews"] = projected_reviews
    projected["revision"] = 2 + len(projected_reviews)
    intent = projected.get("intent")
    requested_role = intent.get("requested_role") if isinstance(intent, Mapping) else None
    quorum = 2 if requested_role in {"Approver", "Owner"} else 1
    approvals = sum(item["decision"] == "approve" for item in projected_reviews)
    if rejected:
        projected["state"] = "rejected"
    elif approvals >= quorum:
        projected["state"] = "approved"
    return projected


def assignment_projection_item(assignment: Mapping[str, object]) -> dict[str, object]:
    """Render one validated assignment case for the Operator read projection."""
    intent = assignment.get("intent")
    if not isinstance(intent, Mapping):
        raise IamUnavailableError("assignment projection intent is malformed")
    subject = intent.get("subject")
    duties = intent.get("duty_bindings")
    if (
        not isinstance(subject, Mapping)
        or not isinstance(duties, list)
        or any(not isinstance(item, Mapping) for item in duties)
    ):
        raise IamUnavailableError("assignment projection fields are malformed")
    return {
        "subject": {
            "provider": subject.get("provider"),
            "subject_id": subject.get("subject_id"),
            "display_name": None,
            "username": None,
            "active": None,
        },
        "roles": None,
        "duties": [
            {**dict(item), "responsibility": "accountable", "source": "stewardship"}
            for item in duties
        ],
        "coverage": None,
        "case": dict(assignment),
        "handover": {
            "goal_refs": intent.get("goal_refs", []),
            "state": None,
            "evidence_refs": None,
            "availability": "not_connected",
        },
    }


def reviewed_access_request(
    request: Mapping[str, object],
    review: Mapping[str, object],
) -> dict[str, object]:
    """Apply one validated access review to an inert request projection."""
    payload = review.get("payload")
    if not isinstance(payload, Mapping):
        raise IamUnavailableError("stored access-review proposal payload is malformed")
    principal = payload.get("principal")
    decision = payload.get("decision")
    accepted_at = review.get("accepted_at")
    justification = payload.get("justification")
    if (
        not isinstance(principal, Mapping)
        or not isinstance(principal.get("oid"), str)
        or decision not in {"approve", "reject"}
        or not isinstance(accepted_at, str)
        or not isinstance(justification, str)
    ):
        raise IamUnavailableError("stored access-review proposal is malformed")
    return {
        **request,
        "status": "approved" if decision == "approve" else "rejected",
        "reviewed_by": principal["oid"],
        "reviewed_at": accepted_at,
        "review_justification": justification,
    }

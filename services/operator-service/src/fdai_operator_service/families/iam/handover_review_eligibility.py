"""Recheck prior human reviews before another review can complete a handover."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from fdai_operator_service.families.iam.contracts import (
    DirectoryIdentity,
    HandoverGoalCommand,
    HumanIdentityDirectory,
    IamPrincipal,
)
from fdai_operator_service.families.iam.errors import IamConflictError, IamUnavailableError
from fdai_operator_service.families.iam.handover_postgres import HandoverReviewerEvidenceVerifier
from fdai_operator_service.families.iam.handover_state import _DOCUMENT_REF, _SHA256
from fdai_service_contracts import OperatorRole
from fdai_service_contracts.handover_checklist import HandoverReview


async def revalidate_goal_reviews(
    goal: Mapping[str, Any],
    command: HandoverGoalCommand,
    *,
    directory: HumanIdentityDirectory,
    backup_eligible: Callable[[Mapping[str, Any], IamPrincipal], Awaitable[bool]],
    at: datetime,
) -> None:
    """Recheck this human and retained reviews; token claims alone do not prove current roles."""
    if at.utcoffset() is None:
        raise ValueError("handover reviewer check time MUST include a timezone")
    targets = {
        "owner_review" if command.operation == "accept" else "backup_review": (
            command.principal.oid.strip().casefold()
        ),
    }
    for field in ("owner_review", "backup_review"):
        raw = goal.get(field)
        if raw is None:
            continue
        try:
            review = HandoverReview.model_validate(raw)
        except ValueError as exc:
            raise IamConflictError("prior handover review is malformed") from exc
        if review.reviewed_at > at:
            raise IamConflictError("prior handover review time is in the future")
        targets[field] = review.reviewer_ref.casefold()
    roster = await _current_roster(directory)
    for field, subject in targets.items():
        identity = _reviewer_identity(roster, subject)
        roles = frozenset(OperatorRole(role) for role in identity.roles)
        if field == "owner_review" and OperatorRole.OWNER not in roles:
            raise IamConflictError("prior handover Owner review is no longer eligible")
        if field == "backup_review" and not await backup_eligible(
            goal, IamPrincipal(subject, roles)
        ):
            raise IamConflictError("prior handover backup acknowledgement is no longer eligible")


async def reader_evidence_current(
    goal: Mapping[str, Any],
    principal: IamPrincipal,
    *,
    directory: HumanIdentityDirectory,
    verifier: object,
) -> bool:
    """Join current role-group membership to each document ACL; never trust a duty as access."""
    if not isinstance(verifier, HandoverReviewerEvidenceVerifier):
        return False
    identity = _reviewer_identity(await _current_roster(directory), principal.oid)
    roles = tuple(sorted(role.value for role in principal.roles if role.value in identity.roles))
    if not roles:
        return False
    evidence = goal.get("evidence")
    if not isinstance(evidence, list) or len(evidence) > 64:
        raise IamUnavailableError("handover reviewer document evidence is malformed")
    checked: set[tuple[str, str]] = set()
    for item in evidence:
        if not isinstance(item, Mapping):
            raise IamUnavailableError("handover reviewer document evidence is malformed")
        reference, digest = item.get("evidence_ref"), item.get("digest")
        if (
            not isinstance(reference, str)
            or _DOCUMENT_REF.fullmatch(reference) is None
            or not isinstance(digest, str)
            or _SHA256.fullmatch(digest) is None
        ):
            raise IamUnavailableError("handover reviewer document evidence is malformed")
        if (reference, digest) in checked:
            continue
        checked.add((reference, digest))
        _, document_id, version_id = reference.split(":")
        if not await verifier.verify_review(
            principal_id=str(goal["subject_ref"]),
            document_id=UUID(document_id),
            version_id=UUID(version_id),
            source_sha256=digest,
            reviewer_id=identity.subject_id,
            reviewer_roles=roles,
            reviewer_group_ids=identity.group_ids,
        ):
            return False
    return True


async def _current_roster(directory: HumanIdentityDirectory) -> Sequence[DirectoryIdentity]:
    try:
        roster = await directory.list_role_roster({}, limit=500)
    except Exception as exc:
        raise IamUnavailableError("current handover reviewer roles are unavailable") from exc
    if len(roster) >= 500:
        raise IamUnavailableError("handover reviewer roster exceeds its bounded read")
    return roster


def _reviewer_identity(roster: Sequence[DirectoryIdentity], subject: str) -> DirectoryIdentity:
    matches = [
        identity
        for identity in roster
        if identity.subject_id.casefold() == subject.casefold()
        and identity.provider == "entra"
        and identity.principal_type == "person"
    ]
    if len(matches) != 1 or not matches[0].active:
        raise IamConflictError("handover reviewer no longer has current identity evidence")
    identity = matches[0]
    try:
        frozenset(OperatorRole(role) for role in identity.roles)
    except ValueError as exc:
        raise IamUnavailableError("handover reviewer role evidence is malformed") from exc
    if (
        not isinstance(identity.group_ids, tuple)
        or len(identity.group_ids) > 500
        or any(
            not isinstance(group, str) or not group or group != group.strip() or len(group) > 256
            for group in identity.group_ids
        )
    ):
        raise IamUnavailableError("handover reviewer group evidence is malformed")
    return identity


__all__ = ["reader_evidence_current", "revalidate_goal_reviews"]

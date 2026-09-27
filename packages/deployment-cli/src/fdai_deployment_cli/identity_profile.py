"""Sanitized readiness contract for the standalone Entra identity operation."""

from __future__ import annotations

from dataclasses import dataclass

from fdai_deployment_cli.contracts import canonical_digest


@dataclass(frozen=True, slots=True)
class IdentityProfileEvidence:
    """Value-free readback facts; ``None`` means the provider read was unavailable."""

    premium_license_eligible: bool | None
    role_groups_present: bool | None
    role_group_profile_match: bool | None
    conditional_access_policy_present: bool | None
    access_review_present: bool | None
    authentication_method_policy_present: bool | None
    phishing_resistant_method_enabled: bool | None
    azure_policy_assignment_present: bool | None
    human_identity_present: bool | None
    human_approver_authorized: bool | None
    executor_identity_present: bool | None
    executor_is_managed_identity: bool | None
    executor_profile_match: bool | None
    human_executor_separated: bool | None

    def __post_init__(self) -> None:
        if any(
            value is not None and type(value) is not bool
            for value in (
                self.premium_license_eligible,
                self.role_groups_present,
                self.role_group_profile_match,
                self.conditional_access_policy_present,
                self.access_review_present,
                self.authentication_method_policy_present,
                self.phishing_resistant_method_enabled,
                self.azure_policy_assignment_present,
                self.human_identity_present,
                self.human_approver_authorized,
                self.executor_identity_present,
                self.executor_is_managed_identity,
                self.executor_profile_match,
                self.human_executor_separated,
            )
        ):
            raise ValueError("identity profile evidence values MUST be booleans or unknown")


@dataclass(frozen=True, slots=True)
class IdentityProfileObservation:
    """Sanitized read-only identity posture with stable fail-closed blockers."""

    evidence: IdentityProfileEvidence
    blockers: tuple[str, ...]

    @classmethod
    def from_evidence(cls, evidence: IdentityProfileEvidence) -> IdentityProfileObservation:
        """Classify every required readback without exposing provider values."""

        blockers: list[str] = []
        _classify(
            blockers,
            evidence.premium_license_eligible,
            unavailable="premium_license_readback_unavailable",
            absent="premium_license_ineligible",
        )
        _classify(
            blockers,
            evidence.role_groups_present,
            unavailable="role_group_readback_unavailable",
            absent="role_group_missing",
        )
        if evidence.role_groups_present is True:
            _classify(
                blockers,
                evidence.role_group_profile_match,
                unavailable="role_group_readback_unavailable",
                absent="role_group_profile_mismatch",
            )
        _classify(
            blockers,
            evidence.conditional_access_policy_present,
            unavailable="conditional_access_readback_unavailable",
            absent="conditional_access_policy_missing",
        )
        _classify(
            blockers,
            evidence.access_review_present,
            unavailable="access_review_readback_unavailable",
            absent="access_review_missing",
        )
        _classify(
            blockers,
            evidence.authentication_method_policy_present,
            unavailable="authentication_method_policy_readback_unavailable",
            absent="authentication_method_policy_missing",
        )
        if evidence.authentication_method_policy_present is True:
            _classify(
                blockers,
                evidence.phishing_resistant_method_enabled,
                unavailable="authentication_method_policy_readback_unavailable",
                absent="phishing_resistant_method_missing",
            )
        _classify(
            blockers,
            evidence.azure_policy_assignment_present,
            unavailable="azure_policy_assignment_readback_unavailable",
            absent="azure_policy_assignment_missing",
        )
        _classify(
            blockers,
            evidence.human_identity_present,
            unavailable="human_identity_readback_unavailable",
            absent="human_identity_missing",
        )
        if evidence.human_identity_present is True:
            _classify(
                blockers,
                evidence.human_approver_authorized,
                unavailable="human_approver_membership_readback_unavailable",
                absent="human_approver_membership_missing",
            )
        _classify(
            blockers,
            evidence.executor_identity_present,
            unavailable="executor_identity_readback_unavailable",
            absent="executor_identity_missing",
        )
        if evidence.executor_identity_present is True:
            _classify(
                blockers,
                evidence.executor_is_managed_identity,
                unavailable="executor_identity_readback_unavailable",
                absent="executor_is_not_managed_identity",
            )
            if evidence.executor_is_managed_identity is True:
                _classify(
                    blockers,
                    evidence.executor_profile_match,
                    unavailable="executor_identity_readback_unavailable",
                    absent="executor_profile_mismatch",
                )
        if evidence.human_identity_present is True and evidence.executor_identity_present is True:
            _classify(
                blockers,
                evidence.human_executor_separated,
                unavailable="human_executor_separation_unavailable",
                absent="human_executor_not_separated",
            )
        return cls(evidence=evidence, blockers=tuple(blockers))

    @property
    def ready(self) -> bool:
        """Return whether every required profile and identity readback passed."""

        return not self.blockers

    @property
    def digest(self) -> str:
        """Bind the exact sanitized observation used by the mutation preflight."""

        return canonical_digest(self._projection())

    def to_mapping(self) -> dict[str, object]:
        """Return only generic booleans, stable blockers, and an opaque digest."""

        projection = self._projection()
        projection["profile_digest"] = canonical_digest(projection)
        return projection

    def _projection(self) -> dict[str, object]:
        evidence = self.evidence
        return {
            "schema_version": "fdai.identity-profile-observation.v1",
            "premium_license": _fact(evidence.premium_license_eligible, "eligible"),
            "role_groups": {
                "readback_available": evidence.role_groups_present is not None,
                "all_present": evidence.role_groups_present is True,
                "profile_match": evidence.role_group_profile_match is True,
            },
            "conditional_access": _fact(
                evidence.conditional_access_policy_present, "policy_present"
            ),
            "access_review": _fact(evidence.access_review_present, "definition_present"),
            "authentication_method_policy": {
                **_fact(evidence.authentication_method_policy_present, "policy_present"),
                "phishing_resistant_method_enabled": bool(
                    evidence.phishing_resistant_method_enabled
                ),
            },
            "azure_policy": _fact(evidence.azure_policy_assignment_present, "assignment_present"),
            "identity_separation": {
                "human_readback_available": evidence.human_identity_present is not None,
                "human_present": evidence.human_identity_present is True,
                "human_approver_authorized": evidence.human_approver_authorized is True,
                "executor_readback_available": evidence.executor_identity_present is not None,
                "executor_present": evidence.executor_identity_present is True,
                "executor_is_managed_identity": evidence.executor_is_managed_identity is True,
                "executor_profile_match": evidence.executor_profile_match is True,
                "human_executor_separated": evidence.human_executor_separated is True,
            },
            "blockers": list(self.blockers),
            "ready": self.ready,
            "mutation_performed": False,
        }


def _classify(
    blockers: list[str],
    value: bool | None,
    *,
    unavailable: str,
    absent: str,
) -> None:
    if value is None:
        if unavailable not in blockers:
            blockers.append(unavailable)
    elif not value:
        blockers.append(absent)


def _fact(value: bool | None, field: str) -> dict[str, bool]:
    return {"readback_available": value is not None, field: value is True}

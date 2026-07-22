"""Role enum + capability matrix tests.

Guards against silent drift between the code matrix and the design doc's
[§ 3 Persona → Action Matrix]
(../../docs/roadmap/interfaces/user-rbac-and-identity.md#3-persona--action-matrix).
"""

from __future__ import annotations

import pytest

from fdai.core.rbac.roles import (
    ROLE_CAPABILITIES,
    Capability,
    Role,
    capabilities_for,
    has_capability,
)


class TestRoleEnum:
    def test_all_five_roles_present(self) -> None:
        assert set(Role) == {
            Role.READER,
            Role.CONTRIBUTOR,
            Role.APPROVER,
            Role.OWNER,
            Role.BREAK_GLASS,
        }

    def test_role_string_values_match_app_role_declarations(self) -> None:
        # Values are the App Role strings assigned in the Entra
        # `fdai-api` app registration. Renaming ANY of these is a
        # coordinated Entra change; the test guards against a silent
        # code-only rename.
        assert Role.READER.value == "Reader"
        assert Role.CONTRIBUTOR.value == "Contributor"
        assert Role.APPROVER.value == "Approver"
        assert Role.OWNER.value == "Owner"
        assert Role.BREAK_GLASS.value == "BreakGlass"

    def test_role_enum_is_stringly_typed(self) -> None:
        assert Role("Approver") is Role.APPROVER
        with pytest.raises(ValueError):
            Role("SuperAdmin")


class TestCapabilityMatrix:
    def test_reader_has_only_view(self) -> None:
        assert ROLE_CAPABILITIES[Role.READER] == frozenset({Capability.VIEW_CONSOLE})

    def test_contributor_extends_reader(self) -> None:
        contributor = ROLE_CAPABILITIES[Role.CONTRIBUTOR]
        assert ROLE_CAPABILITIES[Role.READER] <= contributor
        assert Capability.AUTHOR_DRAFT_PR in contributor
        assert Capability.START_READ_INVESTIGATION in contributor
        # Contributor MUST NOT hold approver-tier caps.
        assert Capability.REVIEW_GOVERNANCE_PR not in contributor
        assert Capability.APPROVE_QUORUM_PROMOTION not in contributor

    def test_approver_extends_contributor(self) -> None:
        approver = ROLE_CAPABILITIES[Role.APPROVER]
        assert ROLE_CAPABILITIES[Role.CONTRIBUTOR] <= approver
        for cap in (
            Capability.REVIEW_GOVERNANCE_PR,
            Capability.APPROVE_QUORUM_PROMOTION,
            Capability.APPROVE_EXEMPTION,
            Capability.APPROVE_OVERRIDE,
            Capability.APPROVE_RUNTIME_HIL,
        ):
            assert cap in approver
        # Approver MUST NOT hold owner-tier caps.
        assert Capability.TRIGGER_KILL_SWITCH not in approver
        assert Capability.MANAGE_GROUP_MEMBERSHIP not in approver
        assert Capability.APPLY_INFRA_IAC not in approver

    def test_owner_extends_approver_and_adds_owner_caps(self) -> None:
        owner = ROLE_CAPABILITIES[Role.OWNER]
        assert ROLE_CAPABILITIES[Role.APPROVER] <= owner
        assert Capability.TRIGGER_KILL_SWITCH in owner
        assert Capability.MANAGE_GROUP_MEMBERSHIP in owner
        assert Capability.APPLY_INFRA_IAC in owner
        # Owner alone does NOT grant emergency access - that stays with
        # BreakGlass (doc § 2 "Break-Glass is NOT nested inside Owner").
        assert Capability.GRANT_EMERGENCY_ACCESS not in owner

    def test_break_glass_is_isolated_not_a_superset_of_owner(self) -> None:
        bg = ROLE_CAPABILITIES[Role.BREAK_GLASS]
        owner = ROLE_CAPABILITIES[Role.OWNER]
        # Explicit anti-superset check: an Owner-account compromise MUST
        # NOT automatically unlock break-glass grants.
        assert not (owner <= bg)
        # Break-glass caps: view + kill-switch + emergency-access. Nothing else.
        assert bg == frozenset(
            {
                Capability.VIEW_CONSOLE,
                Capability.TRIGGER_KILL_SWITCH,
                Capability.GRANT_EMERGENCY_ACCESS,
            }
        )
        # Break-glass MUST NOT be able to author or approve governance PRs.
        assert Capability.AUTHOR_DRAFT_PR not in bg
        assert Capability.START_READ_INVESTIGATION not in bg
        assert Capability.REVIEW_GOVERNANCE_PR not in bg
        assert Capability.APPROVE_QUORUM_PROMOTION not in bg
        # Break-glass MUST NOT manage group membership or apply IaC.
        assert Capability.MANAGE_GROUP_MEMBERSHIP not in bg
        assert Capability.APPLY_INFRA_IAC not in bg

    def test_matrix_is_immutable(self) -> None:
        # MappingProxyType keeps the matrix unmutable at runtime.
        with pytest.raises(TypeError):
            ROLE_CAPABILITIES[Role.READER] = frozenset()  # type: ignore[index]


class TestCapabilitiesFor:
    def test_empty_iterable_yields_empty_bag(self) -> None:
        assert capabilities_for(()) == frozenset()

    def test_single_role(self) -> None:
        assert capabilities_for([Role.READER]) == ROLE_CAPABILITIES[Role.READER]

    def test_union_across_multiple_roles(self) -> None:
        combo = capabilities_for([Role.APPROVER, Role.BREAK_GLASS])
        assert combo == ROLE_CAPABILITIES[Role.APPROVER] | ROLE_CAPABILITIES[Role.BREAK_GLASS]
        # Combined role bag DOES carry GRANT_EMERGENCY_ACCESS because
        # BreakGlass contributes it.
        assert Capability.GRANT_EMERGENCY_ACCESS in combo


class TestHasCapability:
    def test_true_when_role_covers_capability(self) -> None:
        assert has_capability([Role.OWNER], Capability.MANAGE_GROUP_MEMBERSHIP)

    def test_false_when_no_role_covers(self) -> None:
        assert not has_capability([Role.READER], Capability.MANAGE_GROUP_MEMBERSHIP)

    def test_scans_all_provided_roles(self) -> None:
        # Reader alone lacks GRANT_EMERGENCY_ACCESS, but combined with
        # BreakGlass it appears in the union.
        assert has_capability([Role.READER, Role.BREAK_GLASS], Capability.GRANT_EMERGENCY_ACCESS)

    def test_empty_role_list_is_deny(self) -> None:
        assert not has_capability([], Capability.VIEW_CONSOLE)

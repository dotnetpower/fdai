"""Offline exact identity-control readback tests; no provider access."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.entra_profiles import EntraControlProfile, EntraTargetProfile

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = ROOT / "scripts/deployment/azure"
sys.path.insert(0, str(SCRIPT_DIR))

import genesis_identity_executor  # noqa: E402
import genesis_identity_profile  # noqa: E402

HUMAN = "00000000-0000-0000-0000-000000000001"
EXECUTOR = "00000000-0000-0000-0000-000000000002"
EXECUTOR_CLIENT = "00000000-0000-0000-0000-000000000003"
GROUPS = {
    "readers": "00000000-0000-0000-0000-000000000011",
    "contributors": "00000000-0000-0000-0000-000000000012",
    "approvers": "00000000-0000-0000-0000-000000000013",
    "owners": "00000000-0000-0000-0000-000000000014",
    "break_glass": "00000000-0000-0000-0000-000000000015",
}
CA_ID = "00000000-0000-0000-0000-000000000021"
STRENGTH_ID = "00000000-0000-0000-0000-000000000022"
REVIEW_ID = "00000000-0000-0000-0000-000000000031"
ASSIGNMENT = "/subscriptions/example/providers/policyAssignments/fdai"
DEFINITION = "/providers/policyDefinitions/fdai-deny"
SCOPE = "/subscriptions/example"


@pytest.fixture(autouse=True)
def _executor_context(monkeypatch) -> None:
    monkeypatch.setattr(
        genesis_identity_profile,
        "executor_execution_context",
        lambda _target: nullcontext("executor-digest"),
    )


def _profiles() -> tuple[EntraTargetProfile, EntraControlProfile]:
    controls = EntraControlProfile.from_mapping(
        {
            "schema_version": "fdai.entra-control-profile.v1",
            "premium_service_plan": "AAD_PREMIUM_P2",
            "role_groups": GROUPS,
            "conditional_access_policies": [
                {
                    "policy_id": CA_ID,
                    "include_group_slots": ["approvers", "owners"],
                    "exclude_group_slots": [],
                    "include_users": [],
                    "exclude_users": [],
                    "include_roles": [],
                    "exclude_roles": [],
                    "client_app_types": ["all"],
                    "include_applications": ["All"],
                    "exclude_applications": [],
                    "include_platforms": [],
                    "exclude_platforms": [],
                    "include_locations": [],
                    "exclude_locations": [],
                    "sign_in_risk_levels": [],
                    "user_risk_levels": [],
                    "device_filter_mode": None,
                    "device_filter_rule": None,
                    "grant_operator": "AND",
                    "grant_controls": ["authenticationStrength"],
                    "authentication_strength_id": STRENGTH_ID,
                }
            ],
            "access_reviews": [
                {
                    "definition_id": REVIEW_ID,
                    "group_slot": "owners",
                    "scope_query_type": "MicrosoftGraph",
                    "recurrence_pattern_type": "absoluteMonthly",
                    "recurrence_interval": 1,
                    "recurrence_range_type": "noEnd",
                    "duration_days": 14,
                    "allowed_statuses": ["NotStarted"],
                }
            ],
            "authentication_methods": [
                {
                    "method_id": "fido2",
                    "state": "enabled",
                    "include_group_slots": ["approvers", "owners"],
                }
            ],
            "azure_policy_assignments": [
                {
                    "assignment_id": ASSIGNMENT,
                    "definition_id": DEFINITION,
                    "enforcement_mode": "Default",
                    "scope": SCOPE,
                }
            ],
        }
    )
    target = EntraTargetProfile.from_mapping(
        {
            "schema_version": "fdai.entra-target-profile.v2",
            "environment": "dev",
            "target_binding": "a" * 64,
            "executor_object_id": EXECUTOR,
            "executor_client_id": EXECUTOR_CLIENT,
            "executor_display_name": "id-fdai-dev-executor",
            "executor_azure_config_dir": "/opt/fdai/private/executor-azure",
            "control_profile_digest": controls.digest,
        }
    )
    return target, controls


def _graph(_method: str, path: str):
    if path.startswith("me/transitiveMemberOf"):
        return {"value": [{"id": GROUPS["approvers"]}]}
    if path.startswith("subscribedSkus"):
        return {
            "value": [
                {
                    "capabilityStatus": "Enabled",
                    "servicePlans": [
                        {
                            "servicePlanName": "AAD_PREMIUM_P2",
                            "provisioningStatus": "Success",
                        }
                    ],
                }
            ]
        }
    if path.startswith("identity/conditionalAccess/policies"):
        return {
            "value": [
                {
                    "id": CA_ID,
                    "displayName": "private-policy-name",
                    "state": "enabled",
                    "conditions": {
                        "users": {
                            "includeGroups": [GROUPS["owners"], GROUPS["approvers"]],
                            "excludeGroups": [],
                            "includeUsers": [],
                            "excludeUsers": [],
                            "includeRoles": [],
                            "excludeRoles": [],
                        },
                        "clientAppTypes": ["all"],
                        "applications": {
                            "includeApplications": ["All"],
                            "excludeApplications": [],
                        },
                    },
                    "grantControls": {
                        "operator": "AND",
                        "builtInControls": ["authenticationStrength"],
                        "authenticationStrength": {"id": STRENGTH_ID},
                    },
                }
            ]
        }
    if path.startswith("identityGovernance/accessReviews/definitions"):
        return {
            "value": [
                {
                    "id": REVIEW_ID,
                    "status": "NotStarted",
                    "scope": {
                        "query": f"/groups/{GROUPS['owners']}/transitiveMembers",
                        "queryType": "MicrosoftGraph",
                    },
                    "settings": {
                        "instanceDurationInDays": 14,
                        "recurrence": {
                            "pattern": {"type": "absoluteMonthly", "interval": 1},
                            "range": {"type": "noEnd"},
                        },
                    },
                }
            ]
        }
    assert path.startswith("policies/authenticationMethodsPolicy")
    return {
        "authenticationMethodConfigurations": [
            {
                "id": "fido2",
                "state": "enabled",
                "includeTargets": [
                    {"id": GROUPS["owners"], "targetType": "group"},
                    {"id": GROUPS["approvers"], "targetType": "group"},
                ],
            }
        ]
    }


def _az(arguments: tuple[str, ...]):
    if arguments[:3] == ("policy", "assignment", "list"):
        return [
            {
                "id": ASSIGNMENT,
                "policyDefinitionId": DEFINITION,
                "enforcementMode": "Default",
                "scope": SCOPE,
            }
        ]
    assert arguments[:3] == ("ad", "signed-in-user", "show")
    return {
        "id": HUMAN,
        "displayName": "Private Human Name",
        "userPrincipalName": "private-human@example.com",
    }


def test_full_exact_control_profile_succeeds_and_output_is_sanitized(monkeypatch) -> None:
    target, controls = _profiles()
    names = {value: slot for slot, value in genesis_identity_profile._GROUP_NAMES.items()}
    monkeypatch.setattr(genesis_identity_profile, "_graph", _graph)
    monkeypatch.setattr(genesis_identity_profile, "_az_json", _az)
    monkeypatch.setattr(
        genesis_identity_profile,
        "_single_group",
        lambda name: {"id": GROUPS[names[name]], "displayName": name},
    )
    monkeypatch.setattr(
        genesis_identity_profile,
        "_executor_identity",
        lambda _target: (EXECUTOR, True, True),
    )

    observation, human_id = genesis_identity_profile.observe_identity_profile(target, controls)
    rendered = json.dumps(observation.to_mapping(), sort_keys=True)

    assert observation.ready is True
    assert human_id == HUMAN
    assert observation.blockers == ()
    for private_value in (
        HUMAN,
        EXECUTOR,
        EXECUTOR_CLIENT,
        CA_ID,
        REVIEW_ID,
        GROUPS["owners"],
        "private-policy-name",
        "private-human@example.com",
        "graph.microsoft.com",
        "management.azure.com",
    ):
        assert private_value not in rendered


def test_human_evidence_finishes_before_executor_owned_reads(monkeypatch) -> None:
    target, controls = _profiles()
    phase = "human"
    human_reads: list[str] = []
    executor_reads: set[str] = set()

    def human_identity() -> str:
        assert phase == "human"
        human_reads.append("identity")
        return HUMAN

    def human_approver(_controls: EntraControlProfile) -> bool:
        assert phase == "human"
        assert human_reads == ["identity"]
        human_reads.append("approver")
        return True

    @contextmanager
    def executor_context(_target: EntraTargetProfile):
        nonlocal phase
        assert human_reads == ["identity", "approver"]
        phase = "executor"
        try:
            yield "executor-digest"
        finally:
            phase = "restored"

    def executor_reader(name: str, result):
        def read(*_args):
            assert phase == "executor"
            executor_reads.add(name)
            return result

        return read

    monkeypatch.setattr(genesis_identity_profile, "_human_identity", human_identity)
    monkeypatch.setattr(
        genesis_identity_profile,
        "_human_approver_authorized",
        human_approver,
    )
    monkeypatch.setattr(
        genesis_identity_profile,
        "executor_execution_context",
        executor_context,
    )
    monkeypatch.setattr(
        genesis_identity_profile,
        "_premium_license_eligible",
        executor_reader("premium", True),
    )
    monkeypatch.setattr(
        genesis_identity_profile,
        "_role_groups",
        executor_reader("groups", (True, True)),
    )
    monkeypatch.setattr(
        genesis_identity_profile,
        "_conditional_access_matches",
        executor_reader("conditional-access", True),
    )
    monkeypatch.setattr(
        genesis_identity_profile,
        "_access_reviews_match",
        executor_reader("access-reviews", True),
    )
    monkeypatch.setattr(
        genesis_identity_profile,
        "_authentication_methods_match",
        executor_reader("authentication-methods", (True, True)),
    )
    monkeypatch.setattr(
        genesis_identity_profile,
        "_azure_policy_matches",
        executor_reader("azure-policy", True),
    )
    monkeypatch.setattr(
        genesis_identity_profile,
        "_executor_identity",
        executor_reader("executor-identity", (EXECUTOR, True, True)),
    )

    observation, human_id = genesis_identity_profile.observe_identity_profile(target, controls)

    assert observation.ready is True
    assert human_id == HUMAN
    assert phase == "restored"
    assert executor_reads == {
        "premium",
        "groups",
        "conditional-access",
        "access-reviews",
        "authentication-methods",
        "azure-policy",
        "executor-identity",
    }


def test_executor_context_failure_preserves_human_evidence(monkeypatch) -> None:
    target, controls = _profiles()

    @contextmanager
    def unavailable_context(_target: EntraTargetProfile):
        raise RuntimeError("executor login unavailable")
        yield

    monkeypatch.setattr(genesis_identity_profile, "_graph", _graph)
    monkeypatch.setattr(genesis_identity_profile, "_az_json", _az)
    monkeypatch.setattr(
        genesis_identity_profile,
        "executor_execution_context",
        unavailable_context,
    )
    monkeypatch.setattr(
        genesis_identity_profile,
        "_premium_license_eligible",
        lambda *_args: (_ for _ in ()).throw(AssertionError("executor read attempted")),
    )

    observation, human_id = genesis_identity_profile.observe_identity_profile(target, controls)

    assert human_id == HUMAN
    assert "human_identity_readback_unavailable" not in observation.blockers
    assert "human_approver_membership_readback_unavailable" not in observation.blockers
    assert "premium_license_readback_unavailable" in observation.blockers
    assert "role_group_readback_unavailable" in observation.blockers
    assert "executor_identity_readback_unavailable" in observation.blockers


def test_executor_read_failure_restores_context_and_keeps_human_facts(
    monkeypatch,
) -> None:
    target, controls = _profiles()
    human_config = "/home/test/.azure-human"
    executor_config = "/home/test/.azure-executor"
    monkeypatch.setenv("AZURE_CONFIG_DIR", human_config)

    @contextmanager
    def executor_context(_target: EntraTargetProfile):
        previous = os.environ.get("AZURE_CONFIG_DIR")
        os.environ["AZURE_CONFIG_DIR"] = executor_config
        try:
            yield "executor-digest"
        finally:
            if previous is None:
                os.environ.pop("AZURE_CONFIG_DIR", None)
            else:
                os.environ["AZURE_CONFIG_DIR"] = previous

    monkeypatch.setattr(genesis_identity_profile, "_graph", _graph)
    monkeypatch.setattr(genesis_identity_profile, "_az_json", _az)
    monkeypatch.setattr(
        genesis_identity_profile,
        "executor_execution_context",
        executor_context,
    )
    monkeypatch.setattr(
        genesis_identity_profile,
        "_read_executor_profile_concurrently",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("executor provider failure")),
    )

    observation, human_id = genesis_identity_profile.observe_identity_profile(target, controls)

    assert human_id == HUMAN
    assert os.environ["AZURE_CONFIG_DIR"] == human_config
    assert "human_identity_readback_unavailable" not in observation.blockers
    assert "executor_identity_readback_unavailable" in observation.blockers


def test_missing_executor_application_permissions_do_not_fall_back_to_human(
    monkeypatch,
) -> None:
    target, controls = _profiles()
    names = {value: slot for slot, value in genesis_identity_profile._GROUP_NAMES.items()}
    denied_paths: list[str] = []

    def graph(method: str, path: str):
        if path.startswith(
            (
                "identityGovernance/accessReviews/definitions",
                "policies/authenticationMethodsPolicy",
            )
        ):
            denied_paths.append(path)
            raise PermissionError("executor application permission missing")
        return _graph(method, path)

    monkeypatch.setattr(genesis_identity_profile, "_graph", graph)
    monkeypatch.setattr(genesis_identity_profile, "_az_json", _az)
    monkeypatch.setattr(
        genesis_identity_profile,
        "_single_group",
        lambda name: {"id": GROUPS[names[name]], "displayName": name},
    )
    monkeypatch.setattr(
        genesis_identity_profile,
        "_executor_identity",
        lambda _target: (EXECUTOR, True, True),
    )

    observation, human_id = genesis_identity_profile.observe_identity_profile(target, controls)
    rendered = json.dumps(observation.to_mapping(), sort_keys=True)

    assert human_id == HUMAN
    assert "human_identity_readback_unavailable" not in observation.blockers
    assert "human_approver_membership_readback_unavailable" not in observation.blockers
    assert "access_review_readback_unavailable" in observation.blockers
    assert "authentication_method_policy_readback_unavailable" in observation.blockers
    assert "executor application permission missing" not in rendered
    assert len(denied_paths) == 2


def test_unrelated_controls_never_satisfy_reviewed_profile(monkeypatch) -> None:
    target, controls = _profiles()
    unrelated = "00000000-0000-0000-0000-000000000099"

    def graph(method: str, path: str):
        value = _graph(method, path)
        if path.startswith("identity/conditionalAccess/policies"):
            value["value"][0]["id"] = unrelated
        if path.startswith("identityGovernance/accessReviews/definitions"):
            value["value"][0]["id"] = unrelated
        return value

    def az(arguments: tuple[str, ...]):
        value = _az(arguments)
        if arguments[:3] == ("policy", "assignment", "list"):
            value[0]["id"] = "/subscriptions/example/providers/policyAssignments/unrelated"
        return value

    names = {value: slot for slot, value in genesis_identity_profile._GROUP_NAMES.items()}
    monkeypatch.setattr(genesis_identity_profile, "_graph", graph)
    monkeypatch.setattr(genesis_identity_profile, "_az_json", az)
    monkeypatch.setattr(
        genesis_identity_profile,
        "_single_group",
        lambda name: {"id": GROUPS[names[name]], "displayName": name},
    )
    monkeypatch.setattr(
        genesis_identity_profile,
        "_executor_identity",
        lambda _target: (EXECUTOR, True, True),
    )

    observation, _human_id = genesis_identity_profile.observe_identity_profile(target, controls)

    assert observation.ready is False
    assert "conditional_access_policy_missing" in observation.blockers
    assert "access_review_missing" in observation.blockers
    assert "azure_policy_assignment_missing" in observation.blockers


def test_human_outside_approver_group_is_blocked(monkeypatch) -> None:
    target, controls = _profiles()
    names = {value: slot for slot, value in genesis_identity_profile._GROUP_NAMES.items()}

    def graph(method: str, path: str):
        if path.startswith("me/transitiveMemberOf"):
            return {"value": []}
        return _graph(method, path)

    monkeypatch.setattr(genesis_identity_profile, "_graph", graph)
    monkeypatch.setattr(genesis_identity_profile, "_az_json", _az)
    monkeypatch.setattr(
        genesis_identity_profile,
        "_single_group",
        lambda name: {"id": GROUPS[names[name]], "displayName": name},
    )
    monkeypatch.setattr(
        genesis_identity_profile,
        "_executor_identity",
        lambda _target: (EXECUTOR, True, True),
    )

    observation, _human_id = genesis_identity_profile.observe_identity_profile(target, controls)

    assert observation.ready is False
    assert "human_approver_membership_missing" in observation.blockers


def test_missing_role_group_is_a_clear_preflight_blocker(monkeypatch) -> None:
    target, controls = _profiles()
    names = {value: slot for slot, value in genesis_identity_profile._GROUP_NAMES.items()}
    monkeypatch.setattr(genesis_identity_profile, "_graph", _graph)
    monkeypatch.setattr(genesis_identity_profile, "_az_json", _az)
    monkeypatch.setattr(
        genesis_identity_profile,
        "_single_group",
        lambda name: (
            None if name == "aw-owners" else {"id": GROUPS[names[name]], "displayName": name}
        ),
    )
    monkeypatch.setattr(
        genesis_identity_profile,
        "_executor_identity",
        lambda _target: (EXECUTOR, True, True),
    )

    observation, _human_id = genesis_identity_profile.observe_identity_profile(target, controls)

    assert observation.ready is False
    assert "role_group_missing" in observation.blockers
    assert "role_group_profile_mismatch" not in observation.blockers


def test_missing_read_permissions_remain_unknown_and_blocked(monkeypatch) -> None:
    target, controls = _profiles()
    monkeypatch.setattr(
        genesis_identity_profile,
        "_graph",
        lambda *_args: (_ for _ in ()).throw(ValueError("private provider response")),
    )
    monkeypatch.setattr(
        genesis_identity_profile,
        "_az_json",
        lambda *_args: (_ for _ in ()).throw(ValueError("private tenant response")),
    )
    monkeypatch.setattr(
        genesis_identity_profile,
        "_single_group",
        lambda *_args: (_ for _ in ()).throw(ValueError("private group response")),
    )
    monkeypatch.setattr(
        genesis_identity_profile,
        "_executor_identity",
        lambda *_args: (_ for _ in ()).throw(ValueError("private executor response")),
    )

    observation, human_id = genesis_identity_profile.observe_identity_profile(target, controls)
    rendered = json.dumps(observation.to_mapping(), sort_keys=True)

    assert observation.ready is False
    assert human_id is None
    assert "premium_license_readback_unavailable" in observation.blockers
    assert "role_group_readback_unavailable" in observation.blockers
    assert "conditional_access_readback_unavailable" in observation.blockers
    assert "access_review_readback_unavailable" in observation.blockers
    assert "authentication_method_policy_readback_unavailable" in observation.blockers
    assert "azure_policy_assignment_readback_unavailable" in observation.blockers
    assert "human_identity_readback_unavailable" in observation.blockers
    assert "executor_identity_readback_unavailable" in observation.blockers
    assert "private provider response" not in rendered


def test_managed_identity_with_wrong_profile_fields_is_blocked(monkeypatch) -> None:
    target, controls = _profiles()
    names = {value: slot for slot, value in genesis_identity_profile._GROUP_NAMES.items()}
    monkeypatch.setattr(genesis_identity_profile, "_graph", _graph)
    monkeypatch.setattr(genesis_identity_profile, "_az_json", _az)
    monkeypatch.setattr(
        genesis_identity_profile,
        "_single_group",
        lambda name: {"id": GROUPS[names[name]], "displayName": name},
    )
    monkeypatch.setattr(
        genesis_identity_profile,
        "_executor_identity",
        lambda _target: (EXECUTOR, True, False),
    )

    observation, _human_id = genesis_identity_profile.observe_identity_profile(target, controls)

    assert observation.ready is False
    assert "executor_profile_mismatch" in observation.blockers


def test_control_profile_digest_is_stable() -> None:
    target, controls = _profiles()
    assert target.control_profile_digest == controls.digest
    assert controls.digest == canonical_digest(controls.value)


def test_executor_guid_crosses_graph_boundary_only_through_private_descriptor(
    monkeypatch,
) -> None:
    captured = {}
    monkeypatch.setattr(genesis_identity_executor, "trusted_tool", lambda _name: "/usr/bin/az")

    def run(command, **kwargs):
        captured["command"] = command
        descriptor = kwargs["pass_fds"][0]
        body = os.read(descriptor, 65_536).decode()
        assert EXECUTOR in body
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "value": [
                        {
                            "id": EXECUTOR,
                            "appId": EXECUTOR_CLIENT,
                            "displayName": "id-fdai-dev-executor",
                            "servicePrincipalType": "ManagedIdentity",
                        }
                    ]
                }
            ),
        )

    monkeypatch.setattr(genesis_identity_executor.subprocess, "run", run)

    result = genesis_identity_executor.graph_objects_by_id((EXECUTOR,))

    assert result["value"][0]["id"] == EXECUTOR
    assert EXECUTOR not in json.dumps(captured["command"])


def test_executor_context_binds_exact_graph_token_identity(
    tmp_path,
    monkeypatch,
) -> None:
    target, _controls = _profiles()
    executor_config = tmp_path / "executor-azure"
    executor_config.mkdir(mode=0o700)
    target = replace(target, executor_azure_config_dir=executor_config)
    payload = (
        base64.urlsafe_b64encode(
            json.dumps({"oid": EXECUTOR, "appid": EXECUTOR_CLIENT, "idtyp": "app"}).encode()
        )
        .decode()
        .rstrip("=")
    )
    token = f"header.{payload}.signature"
    monkeypatch.setattr(genesis_identity_executor, "trusted_tool", lambda _name: "/usr/bin/az")
    monkeypatch.setattr(
        genesis_identity_executor.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=token),
    )
    monkeypatch.setattr(
        genesis_identity_executor,
        "azure_active_target_binding",
        lambda: target.target_binding,
    )
    human_config = tmp_path / "human-azure"
    human_config.mkdir(mode=0o700)
    monkeypatch.setenv("AZURE_CONFIG_DIR", str(human_config))

    with genesis_identity_executor.executor_execution_context(target) as digest:
        assert os.environ["AZURE_CONFIG_DIR"] == str(executor_config)
        assert digest == hashlib.sha256(EXECUTOR.casefold().encode()).hexdigest()
        assert token not in digest

    assert os.environ["AZURE_CONFIG_DIR"] == str(human_config)

    with pytest.raises(RuntimeError, match="executor read failed"):
        with genesis_identity_executor.executor_execution_context(target):
            assert os.environ["AZURE_CONFIG_DIR"] == str(executor_config)
            raise RuntimeError("executor read failed")

    assert os.environ["AZURE_CONFIG_DIR"] == str(human_config)

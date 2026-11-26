"""Observer approvals bind the stable recipe, a distinct executor, a single use, and a lock."""

import hashlib
import json
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from fdai.delivery import kubernetes_connector_apply_cli as cli
from fdai.delivery.kubernetes_connector_approval import (
    ObserverApproverGrant,
    SignedObserverApproval,
    sign_approval,
    verify_signed_approval,
)
from fdai.delivery.kubernetes_connector_claim import claim_effect, lease_name
from fdai.delivery.kubernetes_connector_installation import render_observer_installation
from fdai.delivery.kubernetes_connector_planning import propose_observer_deployment

from .test_kubernetes_connector_apply import (
    FakeCluster,
    KubeResult,
    approval_for,
    build_installation,
    fresh_approval,
    run_apply,
)
from .test_kubernetes_connector_apply_cli import LATER, arguments, private
from .test_kubernetes_connector_planning import context
from .test_kubernetes_connector_spool import NOW

EXECUTOR = "runner@example.invalid"


@pytest.fixture
def installation(tmp_path):
    return build_installation(tmp_path, "existing_host")


def signing_material(tmp_path, inputs, *, operations=("apply", "activate", "deactivate")):
    key = Ed25519PrivateKey.generate()
    key_path = private(
        tmp_path / "approver.pem",
        key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode(),
    )
    public = key.public_key().public_bytes_raw()
    grant = ObserverApproverGrant(
        approver_ref="operator@example.invalid",
        key_ref="sha256:" + hashlib.sha256(public).hexdigest(),
        public_key=public.hex(),
        target_ref=inputs.target_ref,
        operations=operations,
        valid_from=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=1),
    )
    return key_path, grant


def signed(tmp_path, installation, *, operation="apply", executor=EXECUTOR):
    inputs, rendered, *_ = installation
    key_path, grant = signing_material(tmp_path, inputs)
    approval = approval_for(inputs, rendered, operation=operation)
    return sign_approval(approval, executor_ref=executor, signing_key=key_path), grant


def test_the_recipe_digest_survives_a_proposal_refresh_but_not_a_recipe_change(
    tmp_path, installation
) -> None:
    inputs, rendered, directory, _ = installation
    base = context()
    refreshed = propose_observer_deployment(
        context(
            requested_method="existing_host",
            target_ref=inputs.target_ref,
            observed_at=NOW,
            expires_at=NOW.replace(minute=11),
            facts=tuple(
                fact.model_copy(
                    update={
                        "target_ref": inputs.target_ref,
                        "observed_at": NOW,
                        "expires_at": NOW.replace(minute=6),
                    }
                )
                for fact in base.facts
            ),
        ),
        now=NOW,
    )
    again = render_observer_installation(inputs, refreshed, now=NOW, material_directory=directory)
    assert again["proposal_digest"] != rendered["proposal_digest"]
    assert again["manifest_digest"] != rendered["manifest_digest"]
    assert again["recipe_digest"] == rendered["recipe_digest"]
    again["documents"][0]["metadata"]["labels"]["extra"] = "changed"
    assert render_digest(again) != rendered["recipe_digest"]


def render_digest(rendered):
    from fdai.delivery.kubernetes_connector_installation import recipe_digest

    return recipe_digest(rendered["documents"])


def test_an_approval_signed_before_a_proposal_refresh_still_applies(installation) -> None:
    inputs, rendered, *_ = installation
    approval = approval_for(inputs, rendered)
    value = dict(rendered, proposal_digest="sha256:" + "1" * 64)
    result = run_apply(installation, FakeCluster(), approval, rendered=value)
    assert result["state"] == "installed_suspended"


def test_signed_approval_is_verified_against_an_enrolled_distinct_executor(
    tmp_path, installation
) -> None:
    item, grant = signed(tmp_path, installation)
    approval = verify_signed_approval(item, grants=[grant], executor_ref=EXECUTOR, now=NOW)
    assert approval.approver_ref == "operator@example.invalid"
    with pytest.raises(ValueError, match="distinct identities"):
        verify_signed_approval(item, grants=[grant], executor_ref="someone-else", now=NOW)
    with pytest.raises(ValueError, match="enrolled approver"):
        verify_signed_approval(item, grants=[], executor_ref=EXECUTOR, now=NOW)
    with pytest.raises(ValueError, match="enrolled approver"):
        verify_signed_approval(
            item,
            grants=[grant.model_copy(update={"revoked": True})],
            executor_ref=EXECUTOR,
            now=NOW,
        )
    with pytest.raises(ValueError, match="enrolled approver"):
        verify_signed_approval(
            item, grants=[grant], executor_ref=EXECUTOR, now=NOW + timedelta(hours=2)
        )
    with pytest.raises(ValueError, match="enrolled approver"):
        verify_signed_approval(
            item,
            grants=[grant.model_copy(update={"operations": ("rollback",)})],
            executor_ref=EXECUTOR,
            now=NOW,
        )


def test_an_approver_cannot_execute_its_own_approval(tmp_path, installation) -> None:
    item, grant = signed(tmp_path, installation, executor="operator@example.invalid")
    with pytest.raises(ValueError, match="distinct identities"):
        verify_signed_approval(
            item, grants=[grant], executor_ref="operator@example.invalid", now=NOW
        )


def test_a_tampered_signed_approval_is_rejected(tmp_path, installation) -> None:
    item, grant = signed(tmp_path, installation)
    body = json.loads(item.model_dump_json())
    body["approval"]["namespace"] = "elsewhere"
    with pytest.raises(ValueError, match="signature is invalid"):
        verify_signed_approval(
            SignedObserverApproval.model_validate(body),
            grants=[grant],
            executor_ref=EXECUTOR,
            now=NOW,
        )


def test_an_approval_is_single_use_and_an_unknown_outcome_is_never_replayed(
    installation,
) -> None:
    inputs, rendered, *_ = installation

    class Failing(FakeCluster):
        def run(self, args, *, manifest, timeout):
            if args[0] == "apply" and "--dry-run=server" not in args and self.calls:
                return KubeResult(1, "connection reset")
            return super().run(args, manifest=manifest, timeout=timeout)

    first = approval_for(inputs, rendered)
    with pytest.raises(ValueError, match="outcome is unknown, so run verify"):
        run_apply(installation, Failing(), first)
    with pytest.raises(ValueError, match="outcome is unknown"):
        run_apply(installation, FakeCluster(), first)
    assert (
        run_apply(installation, FakeCluster(), fresh_approval(inputs, rendered))["state"]
        == "installed_suspended"
    )
    with pytest.raises(ValueError, match="already used; request a fresh approval"):
        run_apply(installation, FakeCluster(), fresh_approval(inputs, rendered))


def test_a_claim_is_exclusive_and_owner_only(tmp_path) -> None:
    claim = claim_effect(tmp_path / "claims", "key", operation="apply", at=NOW)
    assert oct(claim.path.stat().st_mode & 0o777) == "0o600"
    with pytest.raises(ValueError, match="unknown"):
        claim_effect(tmp_path / "claims", "key", operation="apply", at=NOW)


def namespaced():
    return FakeCluster(
        namespaces={"fdai-observers": {"app.kubernetes.io/managed-by": "fdai-observer-install"}}
    )


def test_the_cluster_lease_is_held_only_while_applying_and_released_after(installation) -> None:
    inputs, rendered, *_ = installation
    cluster, audit = namespaced(), []
    run_apply(installation, cluster, approval_for(inputs, rendered), audit)
    created = [call for call, _ in cluster.calls if call[0] == "create"]
    assert len(created) == 1
    assert [call for call, _ in cluster.calls if call[:2] == ["delete", "lease"]]
    assert ("lease", inputs.namespace, lease_name(inputs.name)) not in cluster.objects
    assert {item["lock_scope"] for item in audit if "lock_scope" in item} == {"cluster"}


def test_a_dry_run_takes_no_lease(installation) -> None:
    cluster = namespaced()
    run_apply(installation, cluster, None)
    assert not [call for call, _ in cluster.calls if call[0] in {"create", "replace"}]


def test_a_live_lease_blocks_and_an_expired_lease_is_taken_over(installation) -> None:
    inputs, rendered, *_ = installation
    cluster = namespaced()
    key = ("lease", inputs.namespace, lease_name(inputs.name))
    held = {
        "metadata": {"name": key[2], "namespace": key[1], "resourceVersion": "7"},
        "spec": {
            "holderIdentity": "another-host",
            "leaseDurationSeconds": 600,
            "renewTime": (NOW).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        },
    }
    cluster.objects[key] = held
    with pytest.raises(ValueError, match="holds the cluster lock \\(another-host\\)"):
        run_apply(installation, cluster, approval_for(inputs, rendered))
    assert cluster.effects() == []
    held["spec"]["renewTime"] = (NOW - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    result = run_apply(installation, cluster, fresh_approval(inputs, rendered))
    assert result["state"] == "installed_suspended"
    assert [call for call, _ in cluster.calls if call[0] == "replace"]


def test_the_first_installation_reports_the_host_scope_only(installation) -> None:
    inputs, rendered, *_ = installation
    audit = []
    run_apply(installation, FakeCluster(), approval_for(inputs, rendered), audit)
    assert {item["lock_scope"] for item in audit if "lock_scope" in item} == {"host"}


def test_self_issued_approval_needs_the_explicit_development_flag(tmp_path, monkeypatch) -> None:
    built = build_installation(tmp_path, "existing_host")
    cluster = namespaced()
    monkeypatch.setattr(cli, "_transport", lambda *_: cluster)
    from .test_kubernetes_connector_apply_cli import write_proposal

    write_proposal(tmp_path, built)
    digest = built[1]["recipe_digest"]
    with pytest.raises(ValueError, match="--signed-approval from an enrolled approver"):
        cli.run(
            arguments(
                tmp_path,
                "apply",
                built,
                approve_recipe_digest=digest,
                development_self_approval=False,
            ),
            now=LATER,
        )
    assert cluster.effects() == []
    result = cli.run(arguments(tmp_path, "apply", built, approve_recipe_digest=digest), now=LATER)
    assert result["approval_mode"] == "development_self_issued"


def test_sign_then_apply_with_a_distinct_executor_through_the_cli(tmp_path, monkeypatch) -> None:
    built = build_installation(tmp_path, "existing_host")
    inputs, rendered, *_ = built
    cluster = namespaced()
    monkeypatch.setattr(cli, "_transport", lambda *_: cluster)
    from .test_kubernetes_connector_apply_cli import write_proposal

    write_proposal(tmp_path, built)
    key_path, grant = signing_material(tmp_path, inputs)
    grants = private(tmp_path / "grants.json", json.dumps([grant.model_dump(mode="json")]))
    common = {
        "signing_key": key_path,
        "executor_ref": EXECUTOR,
        "approval_grants": grants,
        "development_self_approval": False,
    }
    with pytest.raises(ValueError, match="equal to the recipe"):
        cli.run(
            arguments(tmp_path, "sign-approval", built, sign_operation="apply", **common),
            now=NOW,
        )
    output = cli.run(
        arguments(
            tmp_path,
            "sign-approval",
            built,
            sign_operation="apply",
            approve_recipe_digest=rendered["recipe_digest"],
            **common,
        ),
        now=NOW,
    )
    approval_file = private(tmp_path / "signed.json", json.dumps(output["signed_approval"]))
    installed = cli.run(
        arguments(tmp_path, "apply", built, signed_approval=approval_file, **common),
        now=LATER,
    )
    assert installed["state"] == "installed_suspended"
    assert installed["approval_mode"] == "signed"
    with pytest.raises(ValueError, match="distinct identities"):
        cli.run(
            arguments(
                tmp_path,
                "apply",
                built,
                signed_approval=approval_file,
                **{**common, "executor_ref": "operator@example.invalid"},
            ),
            now=LATER,
        )

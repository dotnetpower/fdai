from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.lifecycle_plan import LifecyclePlan

from fdai_lifecycle_agent.agent import UNVERIFIED_REJECTIONS
from fdai_lifecycle_agent.dry_run import (
    ChangeSet,
    ChangeSetCalculator,
    CurrentState,
    EntityState,
    Health,
    compute_change_set,
)
from fdai_lifecycle_agent.hub_client import HubProtocolError, SignedPlan
from fdai_lifecycle_agent.inputs import SignedArtifact
from fdai_lifecycle_agent.state import AgentStateError

if TYPE_CHECKING:
    from conftest import Harness

NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)

type Overrides = dict[str, Any]


def _state_file(harness: Harness) -> dict[str, Any]:
    document = json.loads(harness.state_store.path.read_text())
    assert isinstance(document, dict)
    return document


# Scenario: admitted Plan


def test_admitted_plan_reports_sanitized_summary_and_digest(harness: Harness) -> None:
    plan = harness.serve(harness.plan())

    result = harness.poll()

    assert result.outcome == "dry-run-admitted"
    assert result.reported is True
    [(installation_id, plan_id, report)] = harness.hub.reports
    assert (installation_id, plan_id) == ("installation-alpha", plan.plan_id)
    body = report.to_json()
    assert body["outcome"] == "dry-run-admitted"
    assert body["reason_code"] == "dry_run_computed"
    assert body["attempt"] == 1
    assert body["reported_at"] == "2026-10-07T12:00:00Z"
    assert body["exact_plan_digest"] == result.exact_plan_digest
    assert body["exact_plan_digest"] == (
        "sha256:" + hashlib.sha256(plan.signed_payload).hexdigest()
    )
    assert json.loads(str(body["summary"])) == {
        "plan_type": "upgrade",
        "entity_count": 2,
        "create": 0,
        "update": 1,
        "unchanged": 1,
    }
    for identifier in ("core", "operator-api", "installation-alpha", harness.release_digest):
        assert identifier not in str(body["summary"])
    state = _state_file(harness)
    assert state["last_accepted_sequence"] == 8
    assert state["plans"][plan.plan_id]["reported"] is True


def test_dry_run_creates_missing_entities(harness: Harness) -> None:
    harness.current_state = replace(harness.current_state, entities={})
    harness.serve(harness.plan())

    first = harness.poll()

    assert first.outcome == "dry-run-admitted"
    summary = json.loads(harness.hub.reports[0][2].summary)
    assert (summary["create"], summary["update"], summary["unchanged"]) == (2, 0, 0)


def test_pretty_printed_signed_inputs_match_the_canonical_plan_digest(harness: Harness) -> None:
    modes = {"action:scale-service": "enforce", "action:extra": "shadow"}
    release = harness.add_release(harness.manifest(capabilities=modes), pretty=True)
    configuration = harness.add_configuration(
        harness.configuration_document | {"environment": {"replicas": 3}}, pretty=True
    )
    harness.serve(
        harness.plan(target_release_digest=release, configuration_revision_digest=configuration)
    )

    result = harness.poll()

    assert result.outcome == "dry-run-admitted"


def test_plan_can_narrow_but_not_widen_the_local_envelope(harness: Harness) -> None:
    harness.serve(
        harness.plan(
            entity_ids=frozenset({"core"}),
            envelope=harness.maximum_envelope(entity_ids=frozenset({"core"})),
        )
    )

    result = harness.poll()

    assert result.outcome == "dry-run-admitted"
    assert json.loads(harness.hub.reports[0][2].summary)["entity_count"] == 1


# Scenario: rejected Plan


@pytest.mark.parametrize(
    ("overrides", "reason_code"),
    [
        ({"sequence": 3}, "plan_sequence_stale"),
        ({"audience": "installation-beta"}, "plan_audience_mismatch"),
        ({"hub_key_id": "hub-key-revoked", "hub_key_epoch": 2}, "hub_key_revoked"),
        ({"hub_key_epoch": 2}, "hub_key_epoch_mismatch"),
        ({"expires_at": NOW - timedelta(seconds=1)}, "plan_expired"),
        ({"fencing_generation": 3}, "plan_fencing_generation_mismatch"),
        ({"source_state_digest": "f" * 64}, "plan_source_state_stale"),
    ],
)
def test_rejected_plan_records_sequence_and_reports_only_reason(
    harness: Harness, overrides: Overrides, reason_code: str
) -> None:
    state = harness.state_store.load()
    harness.state_store.save(replace(state, last_accepted_sequence=5))
    plan = harness.serve(harness.plan(**overrides))

    result = harness.poll()

    assert (result.outcome, result.reason_code, result.reported) == ("rejected", reason_code, True)
    [(_, _, report)] = harness.hub.reports
    assert report.to_json() | {"reported_at": None} == {
        "attempt": 1,
        "outcome": "rejected",
        "reason_code": reason_code,
        "exact_plan_digest": None,
        "summary": "",
        "reported_at": None,
    }
    durable = _state_file(harness)
    assert plan.sequence in durable["rejected_sequences"]
    assert durable["last_accepted_sequence"] == 5


def test_envelope_wider_than_local_maximum_is_rejected(harness: Harness) -> None:
    harness.serve(harness.plan(envelope=harness.maximum_envelope(destructive_allowed=True)))

    result = harness.poll()

    assert result.reason_code == "plan_envelope_exceeds_local_maximum"
    assert 8 in _state_file(harness)["rejected_sequences"]


def _release_with_modes(harness: Harness, **modes: str) -> str:
    return harness.add_release(harness.manifest(capabilities=modes))


@pytest.mark.parametrize(
    ("release_modes", "plan_mode", "reason_code"),
    [
        ({"action:scale-service": "shadow"}, "enforce", "plan_envelope_exceeds_signed_maximum"),
        ({"action:other": "enforce"}, "enforce", "plan_envelope_exceeds_signed_maximum"),
        ({"action:scale-service": "shadow"}, "shadow", "dry_run_computed"),
    ],
)
def test_signed_release_bounds_the_local_maximum(
    harness: Harness, release_modes: dict[str, str], plan_mode: str, reason_code: str
) -> None:
    release = _release_with_modes(harness, **release_modes)
    harness.serve(
        harness.plan(
            target_release_digest=release,
            envelope=harness.maximum_envelope(capability_modes={"action:scale-service": plan_mode}),
        )
    )

    result = harness.poll()

    assert result.reason_code == reason_code


def test_unverified_rejection_codes_match_admission_and_never_block(harness: Harness) -> None:
    plan = harness.plan()
    pretty = json.dumps(json.loads(plan.signed_payload), indent=2).encode()
    signature = harness.hub_keys["hub-key-active"].sign(pretty)
    observed = set()
    for payload, signed in ((plan.signed_payload, b"\x00" * 64), (pretty, signature)):
        harness.hub.plan = SignedPlan(payload, signed)
        observed.add(harness.poll().reason_code)

    assert observed == UNVERIFIED_REJECTIONS
    assert _state_file(harness)["rejected_sequences"] == []


def test_concurrent_poll_stops_before_contacting_the_hub(harness: Harness) -> None:
    harness.serve(harness.plan())

    with harness.state_store.lock(), pytest.raises(AgentStateError, match="another poll"):
        harness.poll()

    assert harness.hub.fetches == 0


def test_rejected_sequence_is_never_admitted_again(harness: Harness) -> None:
    harness.serve(harness.plan(envelope=harness.maximum_envelope(regions=frozenset({"x"}))))
    harness.poll()

    harness.serve(harness.plan(plan_id="plan-0008-retry"))
    result = harness.poll()

    assert result.reason_code == "plan_sequence_previously_rejected"
    assert result.outcome == "rejected"


def test_unverified_plan_signature_does_not_block_the_sequence(harness: Harness) -> None:
    plan = harness.plan()
    harness.hub.plan = SignedPlan(plan.signed_payload, b"\x00" * 64)

    first = harness.poll()
    repeated = harness.poll()
    harness.serve(plan)
    genuine = harness.poll()

    assert (first.reason_code, first.reported) == ("plan_signature_invalid", True)
    assert repeated.outcome == "already-reported"
    assert genuine.outcome == "dry-run-admitted"
    assert [report.attempt for _, _, report in harness.hub.reports] == [1, 2]
    assert _state_file(harness)["rejected_sequences"] == []


def test_unavailable_input_is_retried_without_repeating_the_same_report(harness: Harness) -> None:
    release = harness.store.releases.pop(harness.release_digest)
    harness.serve(harness.plan())

    first = harness.poll()
    repeated = harness.poll()
    harness.store.releases[harness.release_digest] = release
    admitted = harness.poll()

    assert first.reason_code == "release_unavailable"
    assert repeated.outcome == "already-reported"
    assert admitted.outcome == "dry-run-admitted"
    assert [report.outcome for _, _, report in harness.hub.reports] == [
        "rejected",
        "dry-run-admitted",
    ]
    assert harness.hub.reports[-1][2].attempt == 2


def test_unreadable_input_is_a_retryable_rejection(harness: Harness) -> None:
    harness.store.unreadable = True
    harness.serve(harness.plan())

    result = harness.poll()

    assert result.reason_code == "release_unreadable"
    assert _state_file(harness)["rejected_sequences"] == []


def test_malformed_plan_is_dropped_without_report(harness: Harness) -> None:
    harness.hub.plan = SignedPlan(b'{"plan_id": "x"}', b"signature")

    result = harness.poll()

    assert (result.outcome, result.reported) == ("malformed-plan", False)
    assert harness.hub.reports == []


def test_no_pending_plan_does_nothing(harness: Harness) -> None:
    result = harness.poll()

    assert result.outcome == "no-plan"
    assert harness.hub.reports == []
    assert not harness.state_store.path.exists()


# Scenario: unsigned input


def _spy_change_set(calls: list[str]) -> ChangeSetCalculator:
    def spy(
        plan: LifecyclePlan, entity_images: Mapping[str, frozenset[str]], current: CurrentState
    ) -> ChangeSet:
        calls.append("called")
        return compute_change_set(plan, entity_images, current)

    return spy


@pytest.mark.parametrize("unsigned", ["release", "configuration"])
def test_unsigned_input_is_rejected_before_any_change_is_computed(
    harness: Harness, unsigned: str
) -> None:
    calls: list[str] = []
    if unsigned == "release":
        digest = harness.add_release(harness.release_document | {"note": "x"}, signed=False)
        plan = harness.plan(target_release_digest=digest)
    else:
        digest = harness.add_configuration(
            harness.configuration_document | {"note": "x"}, signed=False
        )
        plan = harness.plan(configuration_revision_digest=digest)
    harness.serve(plan)

    result = harness.poll(compute_change_set=_spy_change_set(calls))

    assert result.reason_code == f"{unsigned}_signature_missing"
    assert calls == []
    assert harness.hub.reports[0][2].summary == ""
    assert 8 in _state_file(harness)["rejected_sequences"]


def _resign(harness: Harness, kind: str, signer: Ed25519PrivateKey) -> Overrides:
    store = harness.store.releases if kind == "release" else harness.store.configurations
    digest = harness.release_digest if kind == "release" else harness.configuration_digest
    store[digest] = SignedArtifact(store[digest].payload, signer.sign(store[digest].payload))
    return {}


def _wrong_release_signer(harness: Harness) -> Overrides:
    return _resign(harness, "release", harness.configuration_key)


def _wrong_configuration_signer(harness: Harness) -> Overrides:
    return _resign(harness, "configuration", harness.release_key)


def _missing_release(harness: Harness) -> Overrides:
    harness.store.releases.clear()
    return {}


def _missing_configuration(harness: Harness) -> Overrides:
    harness.store.configurations.clear()
    return {}


def _tampered_release(harness: Harness) -> Overrides:
    payload = json.dumps(harness.manifest(core_control_plane=harness.image("tampered"))).encode()
    signature = harness.release_key.sign(payload)
    harness.store.releases[harness.release_digest] = SignedArtifact(payload, signature)
    return {}


def _release_image_not_a_digest(harness: Harness) -> Overrides:
    document = harness.manifest(core_control_plane="latest")
    return {"target_release_digest": harness.add_release(document)}


def _release_missing_mandatory_field(harness: Harness) -> Overrides:
    document = harness.manifest()
    del document["deployment_bundle_sha256"]
    return {"target_release_digest": harness.add_release(document)}


def _release_schema_v2(harness: Harness) -> Overrides:
    document = harness.manifest()
    for key in ("installation_agents", "schema", "capabilities", "downtime"):
        del document[key]
    document["schema_version"] = "fdai.runtime-release.v2"
    return {"target_release_digest": harness.add_release(document)}


def _release_capability_mode_unknown(harness: Harness) -> Overrides:
    return {"target_release_digest": _release_with_modes(harness, **{"action:x": "execute"})}


def _configuration_literal_secret(harness: Harness) -> Overrides:
    document = harness.configuration_document | {"environment": {"client_secret": "literal"}}
    return {"configuration_revision_digest": harness.add_configuration(document)}


def _configuration_without_matching_override(harness: Harness) -> Overrides:
    overrides = [{"versions": ">=2.0.0 <3.0.0", "values": {"replicas": 2}}]
    document = harness.configuration_document | {"entity_overrides": overrides}
    return {"configuration_revision_digest": harness.add_configuration(document)}


def _configuration_extra_field(harness: Harness) -> Overrides:
    document = harness.configuration_document | {"note": "x"}
    return {"configuration_revision_digest": harness.add_configuration(document)}


@pytest.mark.parametrize(
    ("mutate", "reason_code"),
    [
        (_wrong_release_signer, "release_signature_invalid"),
        (_missing_release, "release_unavailable"),
        (_tampered_release, "release_digest_mismatch"),
        (_wrong_configuration_signer, "configuration_signature_invalid"),
        (_missing_configuration, "configuration_unavailable"),
        (_release_image_not_a_digest, "release_malformed"),
        (_release_missing_mandatory_field, "release_malformed"),
        (_release_schema_v2, "release_schema_unsupported"),
        (_release_capability_mode_unknown, "release_malformed"),
        (_configuration_literal_secret, "configuration_literal_secret"),
        (_configuration_without_matching_override, "configuration_override_missing"),
        (_configuration_extra_field, "configuration_malformed"),
    ],
)
def test_invalid_signed_inputs_are_rejected(
    harness: Harness, mutate: Callable[[Harness], Overrides], reason_code: str
) -> None:
    calls: list[str] = []
    harness.serve(harness.plan(**mutate(harness)))

    result = harness.poll(compute_change_set=_spy_change_set(calls))

    assert result.reason_code == reason_code
    assert calls == []


def _configuration_with_region(harness: Harness, region: str) -> str:
    schema = harness.configuration_document["schema"]
    assert isinstance(schema, dict)
    region_entry = {
        "default": "korea-central",
        "x-fdai-axis": "Deployment environment",
        "x-fdai-owner": "customer",
    }
    document = harness.configuration_document | {
        "schema": schema | {"region": region_entry},
        "environment": {"region": region},
    }
    return harness.add_configuration(document)


@pytest.mark.parametrize(
    ("region", "reason_code"),
    [("korea-central", "dry_run_computed"), ("japan-east", "plan_envelope_exceeds_signed_maximum")],
)
def test_configured_region_narrows_the_local_maximum(
    harness: Harness, region: str, reason_code: str
) -> None:
    configuration = _configuration_with_region(harness, region)
    harness.serve(harness.plan(configuration_revision_digest=configuration))

    result = harness.poll()

    assert result.reason_code == reason_code


def test_release_without_an_entity_component_is_rejected(harness: Harness) -> None:
    harness.entity_components = harness.entity_components | {
        "core": frozenset({"no-such-component"})
    }
    harness.serve(harness.plan())

    result = harness.poll()

    assert result.reason_code == "release_component_missing"


@pytest.mark.parametrize(
    "running", [(), ("operator-service-1.5.0",)], ids=["no-artifacts", "another-components-image"]
)
def test_entity_on_the_target_release_without_its_own_images_needs_an_update(
    harness: Harness, running: tuple[str, ...]
) -> None:
    artifacts = frozenset(harness.image(label) for label in running)
    harness.current_state = replace(
        harness.current_state,
        entities={"core": EntityState("1.5.0", artifacts, Health.HEALTHY)},
    )
    harness.serve(
        harness.plan(
            entity_ids=frozenset({"core"}),
            envelope=harness.maximum_envelope(entity_ids=frozenset({"core"})),
        )
    )

    harness.poll()

    assert json.loads(harness.hub.reports[0][2].summary)["update"] == 1


def test_local_policy_must_name_components_for_every_envelope_entity(harness: Harness) -> None:
    with pytest.raises(ValueError, match="at least one Release component"):
        harness.settings(entity_components={"core": frozenset({"core-control-plane"})})


# Durable reporting


def test_reported_plan_is_not_reevaluated_or_reported_again(harness: Harness) -> None:
    harness.serve(harness.plan())
    harness.poll()

    result = harness.poll()

    assert result.outcome == "already-reported"
    assert len(harness.hub.reports) == 1


def test_failed_report_is_resent_identically_under_the_same_attempt(harness: Harness) -> None:
    harness.serve(harness.plan())
    harness.hub.report_errors.append(HubProtocolError("Hub report request returned 503"))

    first = harness.poll()
    second = harness.poll()

    assert (first.outcome, first.reported) == ("dry-run-admitted", False)
    assert (second.outcome, second.reported) == ("dry-run-admitted", True)
    sent, resent = harness.hub.attempted
    assert sent == resent
    assert resent.attempt == 1


def test_conflicting_attempt_starts_a_new_attempt_on_the_next_poll(harness: Harness) -> None:
    harness.serve(harness.plan())
    harness.hub.report_errors.append(
        HubProtocolError("Hub report request returned 409", code="report_conflict")
    )

    harness.poll()
    result = harness.poll()

    assert result.reported is True
    assert [report.attempt for report in harness.hub.attempted] == [1, 2]


def test_plan_id_reused_with_other_bytes_is_rejected(harness: Harness) -> None:
    harness.serve(harness.plan())
    harness.poll()

    harness.serve(harness.plan(sequence=9))
    result = harness.poll()

    assert (result.reason_code, result.reported) == ("plan_id_conflict", False)
    assert len(harness.hub.reports) == 1
    assert _state_file(harness)["last_accepted_sequence"] == 8

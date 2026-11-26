"""Fake-mode runtime campaign: exact runtime path, no network, label oracle only."""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts/evaluation/typed_selection_runtime_campaign.py"
)


def _module():
    spec = importlib.util.spec_from_file_location("typed_selection_runtime_campaign", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


async def test_fake_campaign_runs_the_runtime_shadow_path_without_changing_answers() -> None:
    campaign = _module()
    cases = campaign.load_cases()
    sample = (cases[0], cases[20], cases[24], cases[32])
    binding, http = campaign._fake_binding(sample)
    async with http:
        result = await campaign.run_campaign(
            binding=binding,
            cases=sample,
            repeats=1,
            probe_delay_seconds=0.0,
            progress=lambda _message: None,
        )
    rows = result["rows"]
    assert [row["case_id"] for row in rows] == [case.case_id for case in sample]
    assert all(row["unavailable_reason"] is None for row in rows)
    assert all(row["same_outcome"] for row in rows)
    assert all(set(row["gated_document_ids"]) == set(row["expected"]) for row in rows)
    assert all(row["terminal"]["answer_changed"] is False for row in rows)
    with pytest.raises(ValueError, match="every planned decision"):
        campaign.judge(rows, result["event_loop_lag_ms"])


def test_window_assets_and_protocol_agree_on_the_plan() -> None:
    campaign = _module()
    cases = campaign.load_cases()
    assert len(cases) == 64
    assert campaign.REPEATS == 4
    assert {case.language for case in cases} == {"en", "ko"}


def test_live_decision_pacing_preserves_the_total_deadline() -> None:
    campaign = _module()
    assert campaign._decision_pacing_delay(now=10.0, next_start=22.0, deadline=100.0) == 12.0
    assert campaign._decision_pacing_delay(now=22.0, next_start=20.0, deadline=100.0) == 0.0
    with pytest.raises(campaign.CampaignAbortedError, match="total deadline"):
        campaign._decision_pacing_delay(now=90.0, next_start=100.0, deadline=100.0)


def test_live_target_resolves_the_exact_pinned_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    campaign = _module()
    pin = campaign.TypedSelectionShadowPin.load(
        campaign.ROOT / campaign.SHADOW_CONFIG_RELATIVE_PATH
    )
    capability = SimpleNamespace(family=pin.model_family, version=pin.model_version)
    target = campaign.ModelRequestTarget(
        endpoint="https://example.invalid",
        deployment="t2.ontology.council.alpha",
        api_version="2024-10-21",
        model_family=pin.model_family,
    )
    requested: list[str] = []
    monkeypatch.setattr(campaign, "_capability", lambda _resolved, name: capability)

    def target_for_capability(_resolved: object, capability_id: str, **_kwargs: object) -> object:
        requested.append(capability_id)
        return target

    monkeypatch.setattr(campaign, "model_target_for_capability", target_for_capability)
    selected_capability, selected_target = campaign._qualified_live_target(
        resolved=object(),
        pin=pin,
        endpoint=None,
        endpoint_resolver=None,
    )
    assert requested == [pin.model_capability]
    assert selected_capability is capability
    assert selected_target is target


def test_live_target_rejects_bound_family_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    campaign = _module()
    pin = campaign.TypedSelectionShadowPin.load(
        campaign.ROOT / campaign.SHADOW_CONFIG_RELATIVE_PATH
    )
    capability = SimpleNamespace(family=pin.model_family, version=pin.model_version)
    target = campaign.ModelRequestTarget(
        endpoint="https://example.invalid",
        deployment="t2.ontology.council.alpha",
        api_version="2024-10-21",
        model_family="other",
    )
    monkeypatch.setattr(campaign, "_capability", lambda _resolved, _name: capability)
    monkeypatch.setattr(
        campaign,
        "model_target_for_capability",
        lambda *_args, **_kwargs: target,
    )
    with pytest.raises(campaign.CampaignAbortedError, match="qualified family and version"):
        campaign._qualified_live_target(
            resolved=object(),
            pin=pin,
            endpoint=None,
            endpoint_resolver=None,
        )


def test_decision_evidence_is_private_and_digested_beyond_the_canonical_bound(
    tmp_path: Path,
) -> None:
    import hashlib

    campaign = _module()
    rows = [{"case_id": f"case-{index}", "padding": "x" * 512} for index in range(256)]
    path = tmp_path / "decisions.jsonl"
    digest = campaign.write_decisions(path, rows)
    data = path.read_bytes()
    assert len(data) > 65_536
    assert digest == "sha256:" + hashlib.sha256(data).hexdigest()
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        campaign.write_decisions(path, rows)


async def test_abort_retains_partial_rows_and_content_free_failure_classes() -> None:
    import logging

    campaign = _module()
    cases = campaign.load_cases()
    fake, http = campaign._fake_binding(cases)

    class _Unavailable:
        def candidate_proposal_binding(self) -> object:
            return fake.expected_binding

        async def propose_candidate_selection(self, **_kwargs: object) -> object:
            raise RuntimeError("private provider detail")

    failing = campaign.TypedSelectionShadowBinding(
        proposer=_Unavailable(),
        data_handling_policy_digest=fake.data_handling_policy_digest,
        expected_binding=fake.expected_binding,
        budget=fake.budget,
    )
    async with http:
        with pytest.raises(campaign.CampaignAbortedError) as aborted:
            await campaign.run_campaign(
                binding=failing,
                cases=cases[:8],
                repeats=1,
                probe_delay_seconds=0.0,
                progress=lambda _message: None,
            )
    rows = aborted.value.rows
    assert len(rows) == campaign.MAX_CONSECUTIVE_UNAVAILABLE
    assert {row["unavailable_reason"] for row in rows} == {"proposal_unavailable"}
    assert all("private provider detail" not in str(row) for row in rows)

    log = campaign.AdapterFailureLog()
    logger = logging.getLogger("fdai.delivery.azure.llm.semantic_planning")
    logger.addHandler(log)
    try:
        logger.warning(
            "semantic_planning_candidate_failed",
            extra={
                "operation": "candidate_selection",
                "failure_type": "HTTPStatusError",
                "status_code": 429,
            },
        )
        logger.warning("unrelated message", extra={"failure_type": "x"})
    finally:
        logger.removeHandler(log)
    expected = {
        "failure_type": "HTTPStatusError",
        "operation": "candidate_selection",
        "status_code": 429,
    }
    assert dict(log.counts) == {json.dumps(expected, sort_keys=True): 1}

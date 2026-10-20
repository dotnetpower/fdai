"""Governed answer-path campaign mechanics use the actual prepare and consume boundary."""

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fdai.delivery.catalog_search.ontology_selection_errors import (
    GovernedReadError,
    SelectionFailure,
)


def _module():
    script = (
        Path(__file__).resolve().parents[3]
        / "scripts/evaluation/governed_typed_selection_campaign.py"
    )
    spec = importlib.util.spec_from_file_location("governed_typed_selection_campaign", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_runtime_container_preserves_the_loader_string_path(tmp_path: Path) -> None:
    campaign = _module()
    artifact = tmp_path / "resolved-models.json"
    artifact.write_text("{}")
    container = campaign._container(
        {
            "LLM_RESOLVED_MODELS_PATH": str(artifact),
            "LLM_RESOLVED_MODELS_SHA256": "0" * 64,
        }
    )
    assert container.config.llm.resolved_models_path == str(artifact)


async def test_fake_campaign_runs_actual_governed_prepare_and_consume_path() -> None:
    campaign = _module()
    cases = campaign.load_cases()
    sample = (cases[0], cases[16], cases[24], cases[28])
    harness = await campaign._build_runtime(None, governed_read=True)
    await campaign._prepare(harness.runtime, harness.state)
    reader, http = await campaign._reader(
        runtime_env=None,
        cases=sample,
        harness=harness,
        source_revision="0" * 40,
    )
    activation = await campaign._activate_evaluation_pointer(
        reader,
        source_revision="0" * 40,
    )
    failures = campaign.AdapterFailureLog()
    async with http:
        result = await campaign.run_campaign(
            reader=reader,
            harness=harness,
            cases=sample,
            live=False,
            failures=failures,
        )
    rows = result["rows"]
    assert len(rows) == 16
    assert all(row["selected"] == row["expected"] for row in rows)
    assert {row["outcome"] for row in rows} == {"held", "returned"}
    assert not failures.counts
    assert activation["binding_digest"].startswith("sha256:")
    assert reader.registry.store is not harness.state
    assert (
        await harness.state.read_state(
            "typed-selection-read:v1:active:" + campaign._context("check").principal_scope_digest
        )
        is None
    )


@pytest.mark.parametrize(
    "error,outcome,reason",
    [
        (PermissionError("private payload"), "unavailable", "unclassified"),
        (
            GovernedReadError(SelectionFailure.UNSUPPORTED_CONSTRAINT),
            "held",
            "unsupported_constraint",
        ),
        (GovernedReadError(SelectionFailure.CITATION_INVALID), "unavailable", "citation_invalid"),
    ],
)
async def test_observed_outcome_does_not_read_expected_answers(monkeypatch, error, outcome, reason):
    campaign = _module()
    harness = await campaign._build_runtime(None, governed_read=True)
    reader, http = await campaign._reader(
        runtime_env=None, cases=(), harness=harness, source_revision="0" * 40
    )
    case = campaign.load_cases()[0]
    observations = []
    handler = AsyncMock(side_effect=error)
    monkeypatch.setattr(campaign, "prepared_function_handler", lambda *args: handler)
    async with http:
        for expected in (frozenset(), frozenset({"object:Resource:synthetic"})):
            result = await campaign.run_campaign(
                reader=reader,
                harness=harness,
                cases=(replace(case, expected=expected),),
                live=False,
                failures=campaign.AdapterFailureLog(),
            )
            observations.append(
                [
                    (r["outcome"], r["failure_reason"], r["unavailable_reason"])
                    for r in result["rows"]
                ]
            )
    assert observations[0] == observations[1]
    assert all(row[0] == outcome and row[1] == reason for row in observations[0])


async def test_evaluation_admission_rejects_other_binding_and_approval():
    campaign = _module()
    harness = await campaign._build_runtime(None, governed_read=True)
    await campaign._prepare(harness.runtime, harness.state)
    reader, http = await campaign._reader(
        runtime_env=None, cases=(), harness=harness, source_revision="0" * 40
    )
    async with http:
        await campaign._activate_evaluation_pointer(reader, source_revision="0" * 40)
        qualification = reader.registry.campaign_admission.qualification
        admission = reader.registry.campaign_admission
        values = {
            "evidence_digest": qualification.digest,
            "scope_digest": qualification.binding.digest,
            "purpose_id": campaign.READ_QUALIFICATION_PURPOSE,
            "source_revision": "0" * 40,
        }
        assert await admission.admit(**values) is not None
        for key in values:
            assert await admission.admit(**{**values, key: "different"}) is None
        assert await reader.registry.approvals.load_replay("forged", "forged") is None
        with pytest.raises(campaign.CampaignAbortedError, match="reuse"):
            await campaign._activate_evaluation_pointer(reader, source_revision="0" * 40)
        reader.registry = campaign.StateStoreTypedSelectionRead(
            harness.state, admission=None, approvals=None
        )
        with pytest.raises(campaign.CampaignAbortedError, match="disposable"):
            await campaign._activate_evaluation_pointer(reader, source_revision="0" * 40)


async def test_spent_live_windows_stop_before_runtime_or_model_setup(monkeypatch, tmp_path):
    campaign = _module()
    build = AsyncMock()
    monkeypatch.setattr(campaign, "_build_runtime", build)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "campaign",
            "--evidence-dir",
            str(tmp_path),
            "--label",
            "not-a-fresh-window",
            "--runtime-env",
            str(tmp_path / "unused.env"),
        ],
    )
    with pytest.raises(SystemExit) as caught:
        await campaign.main()
    assert caught.value.code == 2
    build.assert_not_awaited()


@pytest.mark.parametrize("kind", [429, 503, "timeout", "ReadTimeout"])
async def test_backpressure_or_deadline_aborts_with_first_partial_row(monkeypatch, kind):
    campaign = _module()
    harness = await campaign._build_runtime(None, governed_read=True)
    reader, http = await campaign._reader(
        runtime_env=None, cases=(), harness=harness, source_revision="0" * 40
    )
    failures = campaign.AdapterFailureLog()

    async def fail(*args):
        if isinstance(kind, int):
            failures.counts[campaign.json.dumps({"status_code": kind})] += 1
            raise GovernedReadError(SelectionFailure.PROPOSAL_UNAVAILABLE)
        if kind == "ReadTimeout":
            failures.counts[campaign.json.dumps({"failure_type": kind})] += 1
            raise GovernedReadError(SelectionFailure.PROPOSAL_UNAVAILABLE)
        raise GovernedReadError(SelectionFailure.PROPOSAL_TIMEOUT)

    monkeypatch.setattr(campaign, "prepared_function_handler", lambda *args: fail)
    async with http:
        with pytest.raises(campaign.CampaignAbortedError) as caught:
            await campaign.run_campaign(
                reader=reader,
                harness=harness,
                cases=campaign.load_cases()[:2],
                live=False,
                failures=failures,
            )
    assert len(caught.value.rows) == 1
    assert caught.value.rows[0]["outcome"] == "unavailable"


@pytest.mark.parametrize(
    "kind,reason",
    [
        ("ValidationError", "proposal_contract_invalid"),
        ("SemanticPlanningResponseValidationError", "proposal_contract_invalid"),
        ("CandidateContextError", "context_unavailable"),
        ("RuntimeError", "adapter_unavailable"),
    ],
)
def test_adapter_schema_or_context_failure_is_not_provider_outage(kind, reason):
    campaign = _module()
    failures = campaign.AdapterFailureLog()
    failures.counts[campaign.json.dumps({"failure_type": kind})] += 1
    assert campaign._adapter_failure(failures, {}) == (reason, False)
    assert campaign._adapter_failure(failures, dict(failures.counts)) == (None, False)


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"candidates": None},
        {"candidates": ["invalid"]},
        {"candidates": [{"id": "synthetic"}]},
        {"candidates": [{"id": "", "object_type": "Resource"}]},
        {"candidates": [{"id": "synthetic", "object_type": True}]},
        {"candidates": [{"id": "x", "object_type": "Resource"}] * 2},
    ],
)
def test_malformed_candidate_result_never_becomes_an_empty_success(value):
    campaign = _module()
    with pytest.raises(ValueError):
        campaign._selected_ids(value)

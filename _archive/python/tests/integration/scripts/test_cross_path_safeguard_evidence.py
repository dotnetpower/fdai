"""Cross-path safeguard evidence contract, builder, and verifier.

The contract is the campaign's honesty record: it must describe the matrix
that actually exists at this revision, including the cells that cannot run.
These tests pin that honesty and the fail-closed behaviour of the two
scripts that consume it.
"""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = REPO_ROOT / "config/cross-path-safeguard-evidence.json"
SCHEMA_PATH = REPO_ROOT / "config/cross-path-safeguard-evidence.schema.json"
VERIFIER_PATH = REPO_ROOT / "scripts/quality/repository/validate-cross-path-safeguard-evidence.py"
BUILDER_PATH = (
    REPO_ROOT / "scripts/quality/repository/build-cross-path-safeguard-evidence-bundle.py"
)

_BASE_REVISION = "0" * 40


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def verifier() -> ModuleType:
    return _load_module(VERIFIER_PATH, "cross_path_verifier")


@pytest.fixture(scope="module")
def builder() -> ModuleType:
    return _load_module(BUILDER_PATH, "cross_path_builder")


@pytest.fixture(scope="module")
def contract() -> Mapping[str, Any]:
    document = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


# -- contract honesty ---------------------------------------------------------


def test_the_shipped_contract_validates(verifier: ModuleType, contract: Mapping[str, Any]) -> None:
    assert verifier.validate_contract(contract) == []


def test_the_matrix_covers_every_path_origin_and_venue(contract: Mapping[str, Any]) -> None:
    expected = {
        f"{path}:{origin}:{venue}"
        for path in ("pr_native", "pr_manual", "direct_api", "tool_call")
        for origin in ("core", "workflow")
        for venue in ("core", "isolated_executor")
    }

    assert {cell["cell_id"] for cell in contract["matrix"]} == expected


def test_pr_manual_is_an_explicit_structural_denial(contract: Mapping[str, Any]) -> None:
    """No ActionType declares pr_manual and no RiskGate axis narrows onto it.

    Representing it as eligible would require inventing a producer, so the
    contract records the denial and its evidence instead.
    """

    cells = [cell for cell in contract["matrix"] if cell["execution_path"] == "pr_manual"]

    assert len(cells) == 4
    for cell in cells:
        assert cell["eligibility"] == "structurally_denied"
        assert cell["denial_reason"] == "path_unreachable_no_action_type_declares_it"
        assert "no production caller" in cell["denial_evidence"]
        assert "action_type_ref" not in cell


def test_the_isolated_venue_is_denied_for_every_non_direct_api_path(
    contract: Mapping[str, Any],
) -> None:
    cells = [
        cell
        for cell in contract["matrix"]
        if cell["execution_venue"] == "isolated_executor"
        and cell["execution_path"] in {"pr_native", "tool_call"}
    ]

    assert len(cells) == 4
    for cell in cells:
        assert cell["eligibility"] == "structurally_denied"
        assert cell["denial_reason"] == "venue_supports_direct_api_effect_authority_only"


def test_every_eligible_cell_names_an_action_type_and_an_observer(
    contract: Mapping[str, Any],
) -> None:
    eligible = [cell for cell in contract["matrix"] if cell["eligibility"] == "eligible"]

    assert len(eligible) == 8
    for cell in eligible:
        assert cell["action_type_ref"].endswith("@1.0.0")
        assert cell["observation_source"] in {
            "azure_vm_power_state",
            "github_pull_request",
            "github_issue",
        }


def test_every_eligible_action_type_ships_in_the_catalog(contract: Mapping[str, Any]) -> None:
    for cell in contract["matrix"]:
        if cell["eligibility"] != "eligible":
            continue
        name, _, _version = cell["action_type_ref"].partition("@")
        assert (REPO_ROOT / "rule-catalog/action-types" / f"{name}.yaml").is_file()


def test_a_prepared_campaign_claims_no_live_evidence(contract: Mapping[str, Any]) -> None:
    assert contract["status"] == "prepared"
    assert contract["evidence_level"] == "contract_only"
    assert contract["execution"]["plan_only_by_default"] is True
    assert contract["execution"]["dispatch_is_not_success"] is True
    assert contract["observation"]["allow_synthetic_evidence"] is False
    assert contract["residuals"]


def test_the_declared_denial_classes_match_the_shipped_code(
    contract: Mapping[str, Any],
) -> None:
    from fdai.core.executor.effect_observation import UNKNOWN_OUTCOMES
    from fdai.core.executor.safeguards import EVIDENCE_CITATION, SEVEN_SAFEGUARDS

    classes = contract["denial_classes"]

    assert set(classes["core_pre_dispatch"]) == set(SEVEN_SAFEGUARDS) | {EVIDENCE_CITATION}
    assert set(classes["observation_hold"]) == {outcome.value for outcome in UNKNOWN_OUTCOMES}


# -- verifier fail-closed behaviour -------------------------------------------


@pytest.mark.parametrize(
    ("mutate", "fragment"),
    (
        (lambda c: c["matrix"].pop(), "matrix"),
        (
            lambda c: c["matrix"].__setitem__(0, {**c["matrix"][0], "cell_id": "bogus:core:core"}),
            "does not match its own axes",
        ),
        (lambda c: c.__setitem__("evidence_level", "live_execution"), "produced no live effect"),
        (lambda c: c.__setitem__("residuals", []), "residuals"),
    ),
)
def test_a_dishonest_contract_is_refused(
    verifier: ModuleType,
    contract: Mapping[str, Any],
    mutate: Any,
    fragment: str,
) -> None:
    """Either layer may catch a mutation; neither may let one pass.

    The schema fires first on shape violations and short-circuits the
    semantic pass, so the assertion names the offending concern rather than
    one layer's exact wording.
    """

    mutated = json.loads(json.dumps(contract))
    mutate(mutated)

    errors = verifier.validate_contract(mutated)

    assert errors, "a dishonest contract was accepted"
    assert any(fragment in error for error in errors), errors


def test_a_live_campaign_may_not_keep_residuals(
    verifier: ModuleType,
    contract: Mapping[str, Any],
) -> None:
    mutated = json.loads(json.dumps(contract))
    mutated["status"] = "complete"
    mutated["evidence_level"] = "live_execution"

    errors = verifier.validate_contract(mutated)

    assert any("MUST NOT still carry residuals" in error for error in errors)


# -- builder fail-closed behaviour --------------------------------------------


def _receipt(kind: str, cell_id: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "cell_id": cell_id,
        "base_revision": _BASE_REVISION,
        "recorded_at": "2026-09-13T12:00:00Z",
        "synthetic": False,
        "authority_class": "no_authority",
        "content": {"detail": "focused test receipt"},
    }


def _write(directory: Path, name: str, payload: Any) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(payload)
    (directory / name).write_text(text, encoding="utf-8")


def _complete_receipts(directory: Path, contract: Mapping[str, Any]) -> None:
    for kind in sorted(
        {
            "approval",
            "revision_pin",
            "deployment_preflight",
            "rollback",
            "cleanup",
        }
    ):
        _write(directory, f"{kind}.json", _receipt(kind, f"campaign:{kind}:all"))
    for cell in contract["matrix"]:
        if cell["eligibility"] != "eligible":
            continue
        _write(
            directory,
            f"matrix-{cell['cell_id'].replace(':', '-')}.json",
            _receipt("matrix_cell", cell["cell_id"]),
        )
        _write(
            directory,
            f"observation-{cell['cell_id'].replace(':', '-')}.json",
            _receipt("observation", cell["cell_id"]),
        )
    for group, names in contract["denial_classes"].items():
        for name in names:
            _write(
                directory,
                f"denial-{group}-{name}.json".replace("_", "-"),
                _receipt("denial_class", f"{group}:{name}"),
            )


def test_a_complete_receipt_set_builds_and_verifies(
    builder: ModuleType,
    verifier: ModuleType,
    contract: Mapping[str, Any],
    tmp_path: Path,
) -> None:
    receipts = tmp_path / "receipts"
    _complete_receipts(receipts, contract)
    output = tmp_path / "bundle.json"

    bundle = builder.build(
        receipt_dir=receipts,
        output_path=output,
        campaign_id="focused-test",
        base_revision=_BASE_REVISION,
    )

    assert verifier.validate_bundle(contract, bundle) == []


def test_a_bundle_is_written_once(
    builder: ModuleType,
    contract: Mapping[str, Any],
    tmp_path: Path,
) -> None:
    receipts = tmp_path / "receipts"
    _complete_receipts(receipts, contract)
    output = tmp_path / "bundle.json"
    builder.build(
        receipt_dir=receipts,
        output_path=output,
        campaign_id="focused-test",
        base_revision=_BASE_REVISION,
    )

    with pytest.raises(builder.BundleError, match="written once"):
        builder.build(
            receipt_dir=receipts,
            output_path=output,
            campaign_id="focused-test",
            base_revision=_BASE_REVISION,
        )


def test_a_duplicate_json_key_is_refused(builder: ModuleType, tmp_path: Path) -> None:
    receipts = tmp_path / "receipts"
    _write(receipts, "dupe.json", '{"kind": "approval", "kind": "cleanup"}')

    with pytest.raises(builder.BundleError, match="duplicate JSON key"):
        builder.build(
            receipt_dir=receipts,
            output_path=tmp_path / "bundle.json",
            campaign_id="focused-test",
            base_revision=_BASE_REVISION,
        )


@pytest.mark.parametrize(
    ("mutate", "fragment"),
    (
        (lambda r: r.pop("cell_id"), "omits"),
        (lambda r: r.__setitem__("extra", 1), "unexpected"),
        (lambda r: r.__setitem__("kind", "invented"), "unknown receipt kind"),
        (lambda r: r.__setitem__("authority_class", "execution"), "MUST NOT claim authority"),
        (lambda r: r.__setitem__("base_revision", "1" * 40), "campaign pins"),
    ),
)
def test_a_malformed_receipt_is_refused(
    builder: ModuleType,
    tmp_path: Path,
    mutate: Any,
    fragment: str,
) -> None:
    receipts = tmp_path / "receipts"
    receipt = _receipt("approval", "campaign:approval:all")
    mutate(receipt)
    _write(receipts, "receipt.json", receipt)

    with pytest.raises(builder.BundleError, match=fragment):
        builder.build(
            receipt_dir=receipts,
            output_path=tmp_path / "bundle.json",
            campaign_id="focused-test",
            base_revision=_BASE_REVISION,
        )


def test_an_incomplete_receipt_set_is_refused(
    builder: ModuleType,
    tmp_path: Path,
) -> None:
    receipts = tmp_path / "receipts"
    _write(receipts, "approval.json", _receipt("approval", "campaign:approval:all"))

    with pytest.raises(builder.BundleError, match="omits receipt kinds"):
        builder.build(
            receipt_dir=receipts,
            output_path=tmp_path / "bundle.json",
            campaign_id="focused-test",
            base_revision=_BASE_REVISION,
        )


def test_an_empty_receipt_directory_is_refused(builder: ModuleType, tmp_path: Path) -> None:
    receipts = tmp_path / "receipts"
    receipts.mkdir()

    with pytest.raises(builder.BundleError, match="no receipts found"):
        builder.build(
            receipt_dir=receipts,
            output_path=tmp_path / "bundle.json",
            campaign_id="focused-test",
            base_revision=_BASE_REVISION,
        )


# -- bundle acceptance --------------------------------------------------------


def _built_bundle(
    builder: ModuleType,
    contract: Mapping[str, Any],
    tmp_path: Path,
) -> dict[str, Any]:
    receipts = tmp_path / "receipts"
    _complete_receipts(receipts, contract)
    built = builder.build(
        receipt_dir=receipts,
        output_path=tmp_path / "bundle.json",
        campaign_id="focused-test",
        base_revision=_BASE_REVISION,
    )
    return json.loads(json.dumps(built))


def test_a_tampered_bundle_digest_is_refused(
    builder: ModuleType,
    verifier: ModuleType,
    contract: Mapping[str, Any],
    tmp_path: Path,
) -> None:
    bundle = _built_bundle(builder, contract, tmp_path)
    bundle["campaign_id"] = "someone-elses-campaign"

    errors = verifier.validate_bundle(contract, bundle)

    assert any("does not match its own bytes" in error for error in errors)


def test_a_missing_observation_fails_an_eligible_cell(
    builder: ModuleType,
    verifier: ModuleType,
    contract: Mapping[str, Any],
    tmp_path: Path,
) -> None:
    bundle = _built_bundle(builder, contract, tmp_path)
    bundle["receipts"] = [r for r in bundle["receipts"] if r["kind"] != "observation"]

    errors = verifier.validate_bundle(contract, bundle)

    assert any("has no independent observation" in error for error in errors)


def test_an_unexercised_denial_class_fails_the_bundle(
    builder: ModuleType,
    verifier: ModuleType,
    contract: Mapping[str, Any],
    tmp_path: Path,
) -> None:
    bundle = _built_bundle(builder, contract, tmp_path)
    bundle["receipts"] = [r for r in bundle["receipts"] if r["kind"] != "denial_class"]

    errors = verifier.validate_bundle(contract, bundle)

    assert any("was never exercised" in error for error in errors)


def test_synthetic_evidence_fails_the_bundle(
    builder: ModuleType,
    verifier: ModuleType,
    contract: Mapping[str, Any],
    tmp_path: Path,
) -> None:
    bundle = _built_bundle(builder, contract, tmp_path)
    bundle["receipts"][0]["synthetic"] = True

    errors = verifier.validate_bundle(contract, bundle)

    assert any("is synthetic" in error for error in errors)


def test_a_bundle_pinned_to_another_revision_is_refused(
    builder: ModuleType,
    verifier: ModuleType,
    contract: Mapping[str, Any],
    tmp_path: Path,
) -> None:
    bundle = _built_bundle(builder, contract, tmp_path)
    bundle["base_revision"] = "1" * 40

    errors = verifier.validate_bundle(contract, bundle)

    assert any("pinned revision differs" in error for error in errors)


# -- workflow safety ----------------------------------------------------------


def test_the_campaign_workflow_cannot_execute_an_effect() -> None:
    workflow = (REPO_ROOT / ".github/workflows/cross-path-safeguard-evidence.yml").read_text(
        encoding="utf-8"
    )

    assert "environment: plan-only" in workflow
    assert "if: github.ref == 'refs/heads/main'" in workflow
    assert 'if [ "$REQUESTED_APPLY" != "false" ]; then' in workflow
    assert "execution is not implemented" in workflow
    assert "retention-days: 90" in workflow

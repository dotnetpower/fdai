"""Plan binding, one-time selection, and exact approval display using synthetic evidence."""

from __future__ import annotations

import copy
import io
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/deployment/azure"))

import genesis_approval_prompt as prompt  # noqa: E402
import genesis_runner_image_sku_selection as selection  # noqa: E402
from fdai_deployment_cli.contracts import canonical_digest  # noqa: E402
from fdai_deployment_cli.plan_input import write_plan_input  # noqa: E402
from genesis_checks import CheckError  # noqa: E402
from genesis_runner_image_contract import (  # noqa: E402
    PLAN_JSON_NAME,
    PLAN_NAME,
    REVIEW_NAME,
    add_source_image_version,
    create_review,
)
from genesis_runner_image_review import show_image_vm_selection  # noqa: E402
from genesis_runner_image_sku_choice import choose_image_vm_pair, parse_sku_policy  # noqa: E402
from genesis_runner_image_skus import selection_sizes  # noqa: E402
from tests.integration.scripts.test_genesis_runner_image import (  # noqa: E402
    _inputs,
    _plan_projection,
)
from tests.integration.scripts.test_genesis_runner_image_sku_choice import (  # noqa: E402
    POLICY_PATH,
    restricted,
    sku_rows,
    usage_rows,
)


def prepare(tmp_path: Path) -> tuple[Any, Path, Path]:
    inputs, destination = _inputs(tmp_path)
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    policy = root / "sku-policy.json"
    policy.write_bytes(POLICY_PATH.read_bytes())
    policy.chmod(0o600)
    return inputs, destination, root


def context(inputs: Any, root: Path, capture: Any) -> dict[str, Any]:
    return {
        "subscription_id": str(inputs.terraform_values["subscription_id"]),
        "region": inputs.region,
        "azure_cli": Path("/usr/bin/az"),
        "capture": capture,
        "cwd": root,
        "environment": {},
    }


def capture_factory(inputs: Any, *, blocked_b2s: bool = True) -> tuple[Any, list[str]]:
    calls = []

    def capture(cmd: list[str], **_kwargs: object) -> str:
        assert cmd[:4] == ["/usr/bin/az", "rest", "--method", "get"]
        url = cmd[cmd.index("--url") + 1]
        if "/usages?" in url:
            calls.append("quota")
            return json.dumps({"value": usage_rows()})
        calls.append("skus")
        rows = sku_rows()
        query = cmd[cmd.index("--query") + 1]
        for row in rows:
            row["locations"] = [inputs.region.upper()]
        if blocked_b2s:
            restricted(rows[0])
            rows[0]["restrictions"][0]["values"] = [inputs.region.upper()]
        return json.dumps({"value": [row for row in rows if f"'{row['name']}'" in query]})

    return capture, calls


def selected_inputs(tmp_path: Path) -> tuple[Any, Path, Path]:
    inputs, destination, root = prepare(tmp_path)
    capture, _ = capture_factory(inputs)
    selected = selection.select_image_vm_inputs(
        inputs,
        terraform_root=root,
        destination=destination,
        **{
            key: value
            for key, value in context(inputs, root, capture).items()
            if key not in {"subscription_id", "region"}
        },
    )
    return selected, destination, root


def test_sizes_are_explicit_private_inputs_without_changing_toolchain_or_foundation(
    tmp_path: Path,
) -> None:
    inputs, destination, root = prepare(tmp_path)
    source = copy.deepcopy(inputs.terraform_values)
    foundation_before = (tmp_path / "foundation.json").read_bytes()
    capture, calls = capture_factory(inputs)
    selected = selection.select_image_vm_inputs(
        inputs,
        terraform_root=root,
        destination=destination,
        azure_cli=Path("/usr/bin/az"),
        capture=capture,
        cwd=root,
        environment={},
    )
    assert calls == ["skus", "quota"]
    assert selected.terraform_values == {
        **source,
        "build_vm_size": "Standard_D2ds_v5",
        "verify_vm_size": "Standard_D2ds_v5",
    }
    assert inputs.terraform_values == source
    assert selected.toolchain_digest == inputs.toolchain_digest
    assert selected.profile_digest == inputs.profile_digest
    assert (tmp_path / "foundation.json").read_bytes() == foundation_before
    assert json.loads(destination.read_bytes()) == selected.terraform_values
    assert destination.stat().st_mode & 0o777 == 0o600
    assert selection_sizes(selected.sku_selection) == ("Standard_D2ds_v5", "Standard_D2ds_v5")
    assert selected.sku_selection["capacity_reserved"] is False


def test_input_drift_during_selection_never_overwrites_changed_values(tmp_path: Path) -> None:
    inputs, destination, root = prepare(tmp_path)
    capture, _ = capture_factory(inputs)

    def drift(cmd: list[str], **kwargs: Any) -> str:
        response = capture(cmd, **kwargs)
        if "/usages?" in cmd[cmd.index("--url") + 1]:
            destination.write_text('{"changed":true}')
        return response

    with pytest.raises(CheckError, match="selection_input_changed"):
        selection.select_image_vm_inputs(
            inputs,
            terraform_root=root,
            destination=destination,
            azure_cli=Path("/usr/bin/az"),
            capture=drift,
            cwd=root,
            environment={},
        )
    assert destination.read_text() == '{"changed":true}'


def test_private_snapshots_replay_the_review_bound_choice(tmp_path: Path) -> None:
    selected, _, root = selected_inputs(tmp_path)
    evidence = []
    for name, digest_key in (
        (selection.SKU_EVIDENCE_NAME, "sku_evidence_digest"),
        (selection.QUOTA_EVIDENCE_NAME, "quota_evidence_digest"),
    ):
        path = tmp_path / name
        record = json.loads(path.read_bytes())
        assert path.stat().st_mode & 0o777 == 0o600
        assert canonical_digest(record) == selected.sku_selection[digest_key]
        evidence.append(record["rows"])
    assert choose_image_vm_pair(
        parse_sku_policy((root / "sku-policy.json").read_bytes()),
        region=selected.region,
        rows=evidence[0],
        usages=evidence[1],
    ) == selection_sizes(selected.sku_selection)


@pytest.mark.parametrize("name", [selection.SKU_EVIDENCE_NAME, selection.QUOTA_EVIDENCE_NAME])
def test_existing_evidence_is_not_replaced_by_another_selection(tmp_path: Path, name: str) -> None:
    inputs, destination, root = prepare(tmp_path)
    before = destination.read_bytes()
    evidence = tmp_path / name
    write_plan_input(evidence, {"preserved": True})
    capture, _ = capture_factory(inputs)
    with pytest.raises(FileExistsError):
        selection.select_image_vm_inputs(
            inputs,
            terraform_root=root,
            destination=destination,
            azure_cli=Path("/usr/bin/az"),
            capture=capture,
            cwd=root,
            environment={},
        )
    assert json.loads(evidence.read_bytes()) == {"preserved": True}
    assert destination.read_bytes() == before


def test_sealing_marketplace_version_preserves_an_existing_selection(tmp_path: Path) -> None:
    selected, destination, _ = selected_inputs(tmp_path)
    sealed = add_source_image_version(
        selected,
        version=str(selected.terraform_values["source_image_version"]),
        destination=destination,
    )
    assert sealed.sku_selection == selected.sku_selection
    assert sealed.toolchain_digest == selected.toolchain_digest
    assert sealed.terraform_values == selected.terraform_values


@pytest.mark.parametrize("drift", ["none", "policy", "plan", "quota", "availability"])
def test_apply_rechecks_the_selection_but_does_not_run_auto_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    selected, _, root = selected_inputs(tmp_path)
    capture, calls = capture_factory(selected, blocked_b2s=False)
    projection = _plan_projection(selected.terraform_values)
    if drift == "policy":
        path = root / "sku-policy.json"
        path.write_bytes(path.read_bytes() + b"\n")
    elif drift == "plan":
        next(
            row
            for row in projection["resource_changes"]
            if row["address"].endswith(".verifier")
            and row["type"] == "azurerm_linux_virtual_machine"
        )["change"]["after"]["size"] = "Standard_B2s"

    def current(cmd: list[str], **kwargs: Any) -> str:
        data = json.loads(capture(cmd, **kwargs))
        if drift == "quota" and "/usages?" in cmd[cmd.index("--url") + 1]:
            data["value"][0]["limit"] = 0
        elif drift == "availability" and "/skus?" in cmd[cmd.index("--url") + 1]:
            for row in data["value"]:
                restricted(row)
                row["restrictions"][0]["values"] = [selected.region]
        return json.dumps(data)

    def never_select(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("apply must not rerun automatic selection")

    monkeypatch.setattr(selection, "choose_image_vm_pair", never_select)
    args = {
        **context(selected, root, current),
        "selection": selected.sku_selection,
        "terraform_root": root,
    }
    if drift == "none":
        selection.recheck_image_vm_inputs(json.dumps(projection).encode(), **args)
        assert calls == ["skus", "quota"]
    else:
        with pytest.raises(CheckError):
            selection.recheck_image_vm_inputs(json.dumps(projection).encode(), **args)
        assert calls == ([] if drift in {"policy", "plan"} else ["skus", "quota"])


def make_review(
    tmp_path: Path, *, legacy: bool = False
) -> tuple[Any, dict[str, Any], dict[str, str]]:
    selected, _, _ = selected_inputs(tmp_path)
    work = tmp_path / "runner-image-attempt-1"
    work.mkdir(mode=0o700)
    (work / PLAN_NAME).write_bytes(b"synthetic binary plan")
    (work / PLAN_NAME).chmod(0o600)
    write_plan_input(work / PLAN_JSON_NAME, _plan_projection(selected.terraform_values))
    if legacy:
        selected = replace(selected, sku_selection=None)
    review = create_review(
        directory=work,
        inputs=selected,
        root_digest="a" * 64,
        terraform_digest="b" * 64,
        provider_digest="c" * 64,
    )
    evidence = {key: review[key] for key in ("plan_digest", "review_digest")}
    status = {
        "current_stage": "runner-image-apply",
        "source_commit": selected.source_commit,
        "target_binding": selected.run_digest,
        "foundation_report": {
            "runner_image_plan": {
                **evidence,
                "plan_ref": work.name,
                "effect_summary": {"vm_skus": "untrusted copy"},
            }
        },
    }
    return selected, status, evidence


@pytest.mark.parametrize("legacy", [True, False])
def test_human_review_shows_digest_bound_skus_not_a_mutable_status_copy(
    tmp_path: Path, legacy: bool
) -> None:
    selected, status, evidence = make_review(tmp_path, legacy=legacy)
    output = io.StringIO()
    show_image_vm_selection(status=status, work_dir=tmp_path, evidence=evidence, output=output)
    if legacy:
        assert not output.getvalue()
    else:
        assert "Builder: Standard_D2ds_v5" in output.getvalue()
        assert "Verifier: Standard_D2ds_v5" in output.getvalue()
        assert "not reserved" in output.getvalue()
        assert selected.terraform_values["subscription_id"] not in output.getvalue()


@pytest.mark.parametrize("drift", ["reference", "source", "run", "plan", "review"])
def test_wrong_or_changed_review_is_not_displayed_as_the_approved_selection(
    tmp_path: Path, drift: str
) -> None:
    _, status, evidence = make_review(tmp_path)
    if drift == "reference":
        status["foundation_report"]["runner_image_plan"]["plan_ref"] = "../outside"
    elif drift == "source":
        status["source_commit"] = "f" * 40
    elif drift == "run":
        status["target_binding"] = "f" * 64
    elif drift == "plan":
        evidence["plan_digest"] = "f" * 64
    else:
        path = tmp_path / "runner-image-attempt-1" / REVIEW_NAME
        raw = json.loads(path.read_bytes())
        raw["effect_summary"]["vm_skus"]["verify_vm_size"] = "Standard_B2s"
        path.write_text(json.dumps(raw))
    output = io.StringIO()
    with pytest.raises(ValueError):
        show_image_vm_selection(status=status, work_dir=tmp_path, evidence=evidence, output=output)
    assert not output.getvalue()


def test_expired_review_never_shows_a_current_approval_selection(tmp_path: Path) -> None:
    _, status, evidence = make_review(tmp_path)
    path = tmp_path / "runner-image-attempt-1" / REVIEW_NAME
    review = json.loads(path.read_bytes())
    review["expires_at"] = "2000-01-01T00:00:00+00:00"
    review.pop("review_digest")
    review["review_digest"] = canonical_digest(review)
    evidence["review_digest"] = review["review_digest"]
    path.write_text(json.dumps(review))
    output = io.StringIO()
    with pytest.raises(ValueError, match="expired"):
        show_image_vm_selection(status=status, work_dir=tmp_path, evidence=evidence, output=output)
    assert not output.getvalue()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "future"),
        ("capacity_reserved", True),
        ("capacity_reserved", 0),
        ("policy_digest", "invalid"),
        ("sku_evidence_digest", None),
        ("quota_evidence_digest", []),
        ("build_vm_size", "bad\nlabel"),
        ("verify_vm_size", 2),
        ("checked_at", None),
        ("checked_at", "tomorrow"),
        ("checked_at", "2030-01-01T00:00:00"),
        ("checked_at", "2030-01-01T00:00:00+01:00"),
    ],
)
def test_selection_record_rejects_invalid_labels_and_authority(
    tmp_path: Path, field: str, value: object
) -> None:
    selected, _, _ = selected_inputs(tmp_path)
    record = {**selected.sku_selection, field: value}
    with pytest.raises(CheckError, match="runner_image_sku_plan_invalid"):
        selection_sizes(record)


def test_real_prompt_main_shows_selected_skus_before_reading_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, status, _ = make_review(tmp_path)
    status_path = tmp_path / "status.json"
    write_plan_input(status_path, status)
    output_path = tmp_path / "approval.json"
    output = io.StringIO()
    original = prompt.create_approval

    class Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    def approve(**kwargs: Any) -> dict[str, object]:
        assert "Builder: Standard_D2ds_v5" in output.getvalue()
        assert "Verifier: Standard_D2ds_v5" in output.getvalue()
        return original(**kwargs, input_stream=Tty("runner-image\n"), output_stream=output)

    monkeypatch.setattr(prompt.sys, "stderr", output)
    monkeypatch.setattr(prompt, "current_actor_digest", lambda _binding: "a" * 64)
    monkeypatch.setattr(prompt, "create_approval", approve)
    monkeypatch.setattr(
        prompt.sys,
        "argv",
        ["genesis_approval_prompt.py", "--status", str(status_path), "--output", str(output_path)],
    )
    assert prompt.main() == 0
    assert json.loads(output_path.read_bytes())["stage"] == "runner-image"

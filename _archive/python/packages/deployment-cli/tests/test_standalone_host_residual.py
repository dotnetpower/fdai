from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from fdai_deployment_cli import standalone_host_residual


def test_applied_stage_with_residual_review_dispatches_residual_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "application-receipt.json").write_text("{}", encoding="utf-8")
    (tmp_path / "application-residual-review.json").write_text("{}", encoding="utf-8")
    approval_path = tmp_path / "approval.json"
    records = {
        "context.json": {"context": True},
        "application-review.json": {"original_review": True},
        "application-claim.json": {"original_claim": True},
        "application-residual-review.json": {"residual_review": True},
        "approval.json": {"approval": True},
    }
    expected = {"state": "applied", "operation": "application-residual"}
    monkeypatch.setattr(
        standalone_host_residual,
        "apply_residual_plan",
        lambda **_: expected,
    )

    result = standalone_host_residual.apply_residual_checkpoint(
        Namespace(stage="application", approval=approval_path),
        tmp_path,
        private_json=lambda path, _label: records[path.name],
        validate_approval=lambda *_args, **_kwargs: None,
        managed_identity_login=lambda *_args: None,
        stage_paths=lambda *_args: (tmp_path, tmp_path / "variables.json"),
        activate_stage=lambda *_args: None,
        stage_targets=lambda *_args: (),
        guard_runtime=lambda *_args: None,
        readback_stage=lambda *_args: True,
        absolute_path=lambda path: path,
    )

    assert result is expected

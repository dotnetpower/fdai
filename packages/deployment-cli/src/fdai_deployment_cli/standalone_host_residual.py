"""Dispatch managed-host residual and residual-successor applies."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from fdai_deployment_cli.standalone_residual_apply import apply_residual_plan
from fdai_deployment_cli.standalone_residual_successor import apply_residual_successor


def _original_operation(stage: str, work_dir: Path) -> str:
    """Name the claimed apply a residual review extends.

    A fresh AKS runtime is applied as ``runtime-cluster`` before the ordinary ``runtime``
    operation, so its retained review and claim carry that name until it receives a receipt.
    """

    if (
        stage == "runtime"
        and (work_dir / "runtime-cluster-claim.json").exists()
        and not (work_dir / "runtime-cluster-receipt.json").exists()
    ):
        return "runtime-cluster"
    return stage


def apply_residual_checkpoint(
    args: argparse.Namespace,
    work_dir: Path,
    *,
    private_json: Callable[[Path, str], dict[str, object]],
    validate_approval: Callable[..., None],
    managed_identity_login: Callable[[dict[str, object], Path], None],
    stage_paths: Callable[[str, dict[str, object], Path], tuple[Path, Path]],
    activate_stage: Callable[[str, dict[str, object], Path], None],
    stage_targets: Callable[[str, dict[str, object]], tuple[str, ...]],
    guard_runtime: Callable[[dict[str, object], Path], None],
    readback_stage: Callable[[str, dict[str, object]], bool],
    absolute_path: Callable[[Path], Path],
) -> dict[str, object]:
    """Apply the one current residual review under the shared host boundary."""

    stage = str(args.stage)
    context = private_json(work_dir / "context.json", "standalone host context")
    receipt_path = work_dir / f"{stage}-receipt.json"
    residual_review_path = work_dir / f"{stage}-residual-review.json"
    if receipt_path.exists() and not residual_review_path.exists():
        return private_json(receipt_path, "standalone residual apply receipt")
    original = _original_operation(stage, work_dir)
    original_review = private_json(
        work_dir / f"{original}-review.json", "standalone original plan review"
    )
    original_claim = private_json(
        work_dir / f"{original}-claim.json", "standalone original apply claim"
    )
    residual_review = private_json(residual_review_path, "standalone residual plan review")
    approval = private_json(absolute_path(args.approval), "standalone residual plan approval")
    successor_path = work_dir / f"{stage}-residual-successor-review.json"
    validate_approval(
        private_json(successor_path, "standalone residual successor review")
        if successor_path.exists()
        else residual_review,
        approval,
        context=context,
    )
    managed_identity_login(context, work_dir)
    infra, variables = stage_paths(stage, context, work_dir)
    activate_stage(stage, context, work_dir)
    targets = stage_targets(stage, context)
    if stage == "runtime":
        guard_runtime(context, work_dir)
    if successor_path.exists():
        return apply_residual_successor(
            work_dir=work_dir,
            stage=stage,
            context=context,
            infra=infra,
            variables=variables,
            targets=targets,
            original_review=original_review,
            original_claim=original_claim,
            residual_review=residual_review,
            residual_claim=private_json(
                work_dir / f"{stage}-residual-claim.json", "standalone residual claim"
            ),
            successor_review=private_json(successor_path, "standalone residual successor review"),
            approval=approval,
            effect_readback=lambda: readback_stage(stage, context),
        )
    return apply_residual_plan(
        work_dir=work_dir,
        stage=stage,
        context=context,
        infra=infra,
        variables=variables,
        targets=targets,
        original_review=original_review,
        original_claim=original_claim,
        residual_review=residual_review,
        approval=approval,
        effect_readback=lambda: readback_stage(stage, context),
    )

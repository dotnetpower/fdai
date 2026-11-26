"""CLI: ``python -m fdai.rule_catalog.codegen.new_action_type_cli``.

Emits a shipped-shape :class:`~fdai.shared.contracts.models.OntologyActionType`
YAML. Fork usage::

    python -m fdai.rule_catalog.codegen.new_action_type_cli \\
        --name governance.assign-reviewers \\
        --operation configure \\
        --interface ControlPlane --interface Governance \\
        --rollback state_forward_only \\
        --category ops \\
        --description "Assign reviewers based on affected components." \\
        --out fork/action-types/governance.assign-reviewers.yaml

The generated YAML ships in ``default_mode: shadow`` and passes the
loader's shadow-first invariant. Promotion to enforce is a separate,
audited PR.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fdai.rule_catalog.codegen.new_action_type import (
    ActionTypeSpec,
    PromotionGateSpec,
    render_action_type_yaml,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m fdai.rule_catalog.codegen.new_action_type_cli",
        description="Scaffold a new ontology ActionType YAML.",
    )
    parser.add_argument("--name", required=True, help="ActionType id (dot/dash lowercase).")
    parser.add_argument("--operation", required=True, help="Executor verb (create, update, ...).")
    parser.add_argument(
        "--interface",
        dest="interfaces",
        action="append",
        required=True,
        help="Repeatable ActionInterface (ControlPlane, IdempotentByKey, ...).",
    )
    parser.add_argument(
        "--rollback",
        required=True,
        help="rollback_contract (pr_revert | scripted | pitr | snapshot_restore | state_forward_only).",
    )
    parser.add_argument(
        "--category",
        default="ops",
        help="Top-level bucket (remediation | ops | governance).",
    )
    parser.add_argument("--description", required=True, help="One-line description.")
    parser.add_argument(
        "--irreversible",
        action="store_true",
        help="Set irreversible=true (still requires a rollback_contract).",
    )
    parser.add_argument(
        "--trigger",
        default="rule_violation",
        help="trigger_kind (rule_violation | operator_request | both).",
    )
    parser.add_argument(
        "--execution-path",
        default="pr_native",
        help="pr_native | direct_api | pr_manual.",
    )
    parser.add_argument(
        "--argument-schema",
        default=None,
        help="JSON string describing the operator-request argument schema. "
        "Required when trigger is 'operator_request' or 'both'.",
    )
    parser.add_argument(
        "--min-shadow-days", type=int, default=14, help="promotion_gate.min_shadow_days"
    )
    parser.add_argument("--min-samples", type=int, default=30)
    parser.add_argument("--min-accuracy", type=float, default=0.98)
    parser.add_argument("--max-policy-escapes", type=int, default=0)
    parser.add_argument("--out", default=None, help="Output file path; default stdout.")
    parser.add_argument(
        "--overwrite", action="store_true", help="Overwrite --out if it already exists."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    argument_schema = None
    if args.argument_schema:
        try:
            argument_schema = json.loads(args.argument_schema)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"--argument-schema is not valid JSON: {exc}") from exc

    spec = ActionTypeSpec(
        name=args.name,
        operation=args.operation,
        interfaces=tuple(args.interfaces),
        rollback_contract=args.rollback,
        category=args.category,
        description=args.description,
        irreversible=args.irreversible,
        promotion_gate=PromotionGateSpec(
            min_shadow_days=args.min_shadow_days,
            min_samples=args.min_samples,
            min_accuracy=args.min_accuracy,
            max_policy_escapes=args.max_policy_escapes,
        ),
        trigger_kind=args.trigger,
        execution_path=args.execution_path,
        argument_schema=argument_schema,
        header_comment=(
            f"Fork-generated ActionType {args.name}.",
            "Ships in shadow mode; promote via a separate reviewed PR.",
        ),
    )
    yaml_text = render_action_type_yaml(spec)

    if args.out is None:
        sys.stdout.write(yaml_text)
        return 0
    out_path = Path(args.out)
    if out_path.exists() and not args.overwrite:
        raise SystemExit(f"{out_path} already exists; pass --overwrite to replace.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yaml_text)
    print(f"wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())

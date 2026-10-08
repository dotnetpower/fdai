"""`fdai-lifecycle-hub` command line.

The database URL comes only from `FDAI_LIFECYCLE_HUB_DATABASE_URL` so credentials never appear
in process arguments or shell history.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Sequence
from datetime import timedelta
from functools import partial
from pathlib import Path

from fdai_deployment_cli.lifecycle_plan import SuppressionWindow

from fdai_lifecycle_hub import domain, schemas
from fdai_lifecycle_hub.catalog import load_catalog
from fdai_lifecycle_hub.errors import HubStoreError
from fdai_lifecycle_hub.planning import plan_next
from fdai_lifecycle_hub.signing import (
    generate_development_key,
    load_private_key,
    load_signing_key,
    verify_key_proof,
)
from fdai_lifecycle_hub.store import HubStore

DATABASE_URL_ENV = "FDAI_LIFECYCLE_HUB_DATABASE_URL"
LOOPBACK = "127.0.0.1"

type Handler = Callable[[argparse.Namespace], int]


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    handler: Handler = args.handler
    try:
        return handler(args)
    except (HubStoreError, ValueError) as error:  # ValueError covers pydantic and domain checks.
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fdai-lifecycle-hub")
    commands = parser.add_subparsers(required=True, metavar="command")

    def command(name: str, handler: Handler, help_text: str) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=help_text)
        sub.set_defaults(handler=handler)
        return sub

    command("migrate", _migrate, "create the Hub schema")

    keygen = command("dev-keygen", _dev_keygen, "write a development Hub signing key")
    keygen.add_argument("path", type=Path)

    enroll = command(
        "dev-enroll", _dev_enroll, "sign an enrollment request with a development key and submit it"
    )
    enroll.add_argument("path", type=Path, help="enrollment request without key and time")
    enroll.add_argument("--key", type=Path, required=True, help="installation private key")

    approve = command("approve", _approve, "enroll a pending installation")
    approve.add_argument("installation_id")
    approve.add_argument("--approver", required=True)
    approve.add_argument("--installation-key-id", required=True)

    reject = command("reject", _reject, "reject a pending enrollment")
    reject.add_argument("installation_id")
    reject.add_argument("--approver", required=True)
    reject.add_argument("--reason", required=True, help="a reason code such as unknown_key")

    ownership = command(
        "record-ownership", _record_ownership, "record an Entity's ownership evidence"
    )
    ownership.add_argument("installation_id")
    ownership.add_argument("entity_id")
    ownership.add_argument("path", type=Path)

    manage = command("manage", _manage, "give an Entity its settings, which makes it managed")
    manage.add_argument("installation_id")
    manage.add_argument("entity_id")
    manage.add_argument("path", type=Path, help="Entity override blocks")
    manage.add_argument("--operator", required=True)

    record_state = command("record-state", _record_state, "record a reported-state snapshot")
    record_state.add_argument("installation_id")
    record_state.add_argument("path", type=Path)

    suppress = command("suppress", _suppress, "hold Plans for a scope, starting now")
    suppress.add_argument("installation_id")
    suppress.add_argument(
        "--scope", default="installation", help="installation, entity:<id>, or plan:<type>"
    )
    suppress.add_argument("--minutes", type=int, default=60)

    unsuppress = command("unsuppress", _unsuppress, "lift the active suppressions for a scope")
    unsuppress.add_argument("installation_id")
    unsuppress.add_argument("--scope", default="installation")

    recompute = command("recompute", _recompute, "plan the next Release for an installation")
    recompute.add_argument("installation_id")
    recompute.add_argument("--catalog", type=Path, required=True)
    recompute.add_argument("--key", type=Path, required=True)
    recompute.add_argument("--key-epoch", type=int, default=1)

    show = command("show", _show, "print the open Plan and why the last recompute chose it")
    show.add_argument("installation_id")

    serve = command("serve", _serve, f"serve the agent API on {LOOPBACK}")
    serve.add_argument("--port", type=int, default=8090)
    return parser


def _store() -> HubStore:
    url = os.environ.get(DATABASE_URL_ENV)
    if not url:
        raise SystemExit(f"{DATABASE_URL_ENV} is not set")
    return HubStore.connect(url)


def _print(record: object) -> None:
    json.dump(record, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")


def _migrate(args: argparse.Namespace) -> int:
    _store().create_schema()
    _print({"schema": "created"})
    return 0


def _dev_keygen(args: argparse.Namespace) -> int:
    _print({"public_key": str(generate_development_key(args.path))})
    return 0


def _dev_enroll(args: argparse.Namespace) -> int:
    """Stand in for the installation agent: add the key and time, sign, and submit."""

    template = json.loads(args.path.read_bytes())
    if not isinstance(template, dict):
        raise ValueError("an enrollment request must be a JSON object")
    now = domain.utc_now()
    request = schemas.sign_enrollment(template, load_private_key(args.key), now)
    _store().request_enrollment(request, verify=verify_key_proof, now=now)
    _print(
        {
            "pending": request.installation.installation_id,
            "installation_key_id": request.installation_key_id,
        }
    )
    return 0


def _approve(args: argparse.Namespace) -> int:
    _store().approve(
        args.installation_id,
        approver=args.approver,
        installation_key_id=args.installation_key_id,
        now=domain.utc_now(),
    )
    _print({"enrolled": args.installation_id})
    return 0


def _reject(args: argparse.Namespace) -> int:
    _store().reject(
        args.installation_id, approver=args.approver, reason=args.reason, now=domain.utc_now()
    )
    _print({"rejected": args.installation_id})
    return 0


def _record_ownership(args: argparse.Namespace) -> int:
    evidence = schemas.ownership_json.validate_json(args.path.read_bytes())
    _store().record_ownership(args.installation_id, args.entity_id, evidence, now=domain.utc_now())
    _print({"entity": args.entity_id, "proven": evidence.gap is None, "reason": evidence.gap})
    return 0


def _manage(args: argparse.Namespace) -> int:
    settings = schemas.entity_settings_json.validate_json(args.path.read_bytes())
    covering = _store().manage(
        args.installation_id,
        args.entity_id,
        settings,
        operator=args.operator,
        now=domain.utc_now(),
    )
    _print({"managed": args.entity_id, "settings": settings.digest, "covering_range": covering})
    return 0


def _record_state(args: argparse.Namespace) -> int:
    state = schemas.reported_state_json.validate_json(args.path.read_bytes())
    _store().record_state(args.installation_id, state, now=domain.utc_now())
    _print({"recorded": state.digest})
    return 0


def _suppress(args: argparse.Namespace) -> int:
    if args.minutes < 1:
        raise ValueError("--minutes must be at least 1")
    now = domain.utc_now()
    window = SuppressionWindow(args.scope, now, now + timedelta(minutes=args.minutes))
    _store().add_suppression(args.installation_id, window, now=now)
    _print({"suppressed": window.scope, "until": window.ends_at.isoformat()})
    return 0


def _unsuppress(args: argparse.Namespace) -> int:
    _store().lift_suppressions(args.installation_id, args.scope, now=domain.utc_now())
    _print({"lifted": args.scope})
    return 0


def _recompute(args: argparse.Namespace) -> int:
    planner = partial(
        plan_next,
        catalog=load_catalog(args.catalog),
        key=load_signing_key(args.key, epoch=args.key_epoch),
    )
    outcome = _store().recompute(args.installation_id, planner, now=domain.utc_now())
    _print(schemas.outcome_record(outcome))
    return 0


def _show(args: argparse.Namespace) -> int:
    store = _store()
    plan = store.current_plan(args.installation_id, now=domain.utc_now())
    evaluation = store.last_evaluation(args.installation_id)
    _print(
        {
            "enrollment": store.enrollment_status(args.installation_id),
            "plan": _plan_record(plan) if plan else None,
            "last_evaluation": (
                schemas.evaluation_json.dump_python(evaluation, mode="json") if evaluation else None
            ),
        }
    )
    return 0


def _plan_record(plan: domain.IssuedPlan) -> dict[str, str]:
    return {
        "plan_id": plan.plan_id,
        "target": plan.target_release_id,
        "expires_at": plan.expires_at.isoformat(),
    }


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from fdai_lifecycle_hub.api import create_app

    uvicorn.run(create_app(_store()), host=LOOPBACK, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

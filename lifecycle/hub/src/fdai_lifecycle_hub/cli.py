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
from uuid import UUID

from azure.core.exceptions import AzureError
from fdai_deployment_cli.contracts import load_json_object
from fdai_deployment_cli.lifecycle_native import NativeOwnershipAcceptance
from fdai_deployment_cli.lifecycle_plan import SuppressionWindow
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from fdai_lifecycle_hub import domain, models, schemas
from fdai_lifecycle_hub.catalog import load_catalog
from fdai_lifecycle_hub.catalog_import import load_pinned_export
from fdai_lifecycle_hub.errors import HubStoreError, SchemaMismatchError
from fdai_lifecycle_hub.migrations import migrate, require_schema
from fdai_lifecycle_hub.native_ownership import NativeOwnershipStore
from fdai_lifecycle_hub.native_proofs import NativeProofStore
from fdai_lifecycle_hub.planning import plan_next
from fdai_lifecycle_hub.signing import (
    generate_development_key,
    load_private_key,
    load_public_key,
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
    except (AzureError, SQLAlchemyError) as error:
        print(
            f"{type(error).__name__}: Hub operation failed; verify storage, identity and inputs.",
            file=sys.stderr,
        )
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fdai-lifecycle-hub")
    commands = parser.add_subparsers(required=True, metavar="command")

    def command(name: str, handler: Handler, help_text: str) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=help_text)
        sub.set_defaults(handler=handler, command=name)
        return sub

    command("migrate", _migrate, "create the Hub schema")
    command("prepare", _migrate, "prepare an existing Hub without advancing its reader floor")

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
    ownership.add_argument("--operator", required=True)

    native = command(
        "accept-native-ownership",
        _accept_native_ownership,
        "accept signed native creation evidence with separate operator confirmation",
    )
    native.add_argument("installation_id")
    native.add_argument("path", nargs="?", type=Path, help="private complete acceptance request")
    native.add_argument("--submitted-proof", help="claim digest from the private approval input")
    native.add_argument("--request-id", type=UUID)
    native.add_argument("--settings-digest")
    native.add_argument("--reason")
    native.add_argument("--confirmation")
    native.add_argument("--operator", required=True)

    binding = command(
        "bind-application", _bind_application, "bind an application with a private operator request"
    )
    binding.add_argument("installation_id")
    binding.add_argument("path", type=Path)
    binding.add_argument("--operator", required=True)

    manage = command("manage", _manage, "give an Entity its settings, which makes it managed")
    manage.add_argument("installation_id")
    manage.add_argument("entity_id")
    manage.add_argument("path", type=Path, help="Entity override blocks")
    manage.add_argument("--operator", required=True)
    manage.add_argument("--initial-release", help="override coverage version for an empty Entity")

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
    pinned = command(
        "recompute-pinned",
        _recompute_pinned,
        "plan from an explicitly pinned local Release Hub export",
    )
    pinned.add_argument("installation_id")
    pinned.add_argument("--export", type=Path, required=True)
    pinned.add_argument("--sha256", required=True, help="trusted out-of-band export digest")
    pinned.add_argument("--release-public-key", type=Path, required=True)
    pinned.add_argument("--minimum-revision", type=int, required=True)
    pinned.add_argument("--previous-sha256")
    pinned.add_argument("--key", type=Path, required=True)
    pinned.add_argument("--key-epoch", type=int, default=1)

    show = command(
        "show",
        _show,
        "print the open Plan, why the last recompute chose it, active suppressions, and reports",
    )
    show.add_argument("installation_id")

    serve = command("serve", _serve, f"serve the agent API on {LOOPBACK}")
    serve.add_argument("--port", type=int, default=8090)
    serve.add_argument(
        "--ui",
        type=Path,
        default=None,
        help="built operator UI directory; defaults to ui/dist when it exists",
    )
    return parser


def _store() -> HubStore:
    if "FDAI_HUB_REMOTE_CONFIG" in os.environ:
        from fdai_lifecycle_hub.remote import RemoteConfig, remote_engine

        try:
            config = RemoteConfig.model_validate_json(os.environ["FDAI_HUB_REMOTE_CONFIG"])
        except ValueError:
            raise ValueError("Trusted Lifecycle CLI remote configuration is invalid.") from None
        if config.kind != "target":
            raise ValueError("Trusted Lifecycle CLI requires a target Hub configuration.")
        engine = remote_engine("target")
        require_schema(engine, "lifecycle_hub")
        return HubStore(engine)
    url = os.environ.get(DATABASE_URL_ENV)
    if not url:
        raise SystemExit(f"{DATABASE_URL_ENV} is not set")
    return HubStore.connect(url)


def _print(record: object) -> None:
    json.dump(record, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")


def _migrate(args: argparse.Namespace) -> int:
    store = _store()

    def initialize(connection: Connection) -> None:
        if stale := models.stale_tables(connection):
            raise SchemaMismatchError(f"recreate the Hub database; earlier schema in {stale}")
        models.Base.metadata.create_all(connection)

    prepare = args.command == "prepare"
    migrate(store.engine, "lifecycle_hub", initialize, prepare=prepare)
    _print({"schema": "prepared" if prepare else "created"})
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
    _store().record_ownership(
        args.installation_id,
        args.entity_id,
        evidence,
        operator=args.operator,
        now=domain.utc_now(),
    )
    _print({"entity": args.entity_id, "proven": evidence.gap is None, "reason": evidence.gap})
    return 0


def _accept_native_ownership(args: argparse.Namespace) -> int:
    store = _store()
    selection = (
        args.submitted_proof,
        args.request_id,
        args.settings_digest,
        args.reason,
        args.confirmation,
    )
    if args.path is not None and any(value is not None for value in selection):
        raise ValueError("native_ownership_request_sources_conflict")
    if args.path is None and not all(value is not None for value in selection):
        raise ValueError("native_ownership_request_required")
    try:
        if args.path is not None:
            with args.path.open("rb") as handle:
                body = handle.read(8193)
            load_json_object(body, label="native ownership", max_bytes=8192, strict=True)
            command = NativeOwnershipAcceptance.model_validate_json(body)
        else:
            command = NativeOwnershipAcceptance(
                request_id=args.request_id,
                expected_settings_digest=args.settings_digest,
                proof=NativeProofStore(store).load(args.installation_id, args.submitted_proof),
                reason=args.reason,
                confirmation=args.confirmation,
            )
    except (OSError, ValueError) as error:
        raise ValueError("native_ownership_request_invalid") from error
    result = NativeOwnershipStore(store).accept(
        args.installation_id, command, operator=args.operator, now=domain.utc_now()
    )
    _print({"accepted": True, "changed": result["changed"]})
    return 0


def _bind_application(args: argparse.Namespace) -> int:
    from fdai_lifecycle_hub.execution_settings import ApplicationBindingRequest

    try:
        with args.path.open("rb") as handle:
            body = handle.read(8193)
        load_json_object(body, label="application binding", max_bytes=8192, strict=True)
        command = ApplicationBindingRequest.model_validate_json(body)
    except (OSError, ValueError) as error:
        raise ValueError("application_binding_request_invalid") from error
    result = _store().bind_application(
        args.installation_id, command, operator=args.operator, now=domain.utc_now()
    )
    _print({"bound": True, "changed": result["changed"]})
    return 0


def _manage(args: argparse.Namespace) -> int:
    settings = schemas.entity_settings_json.validate_json(args.path.read_bytes())
    covering = _store().manage(
        args.installation_id,
        args.entity_id,
        settings,
        operator=args.operator,
        now=domain.utc_now(),
        initial_release=args.initial_release,
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


def _recompute_pinned(args: argparse.Namespace) -> int:
    with args.export.open("rb") as handle:
        raw = handle.read(8 * 1024 * 1024 + 1)
    now = domain.utc_now()
    catalog = load_pinned_export(
        raw,
        expected_sha256=args.sha256,
        public_key=load_public_key(args.release_public_key),
        now=now,
        minimum_revision=args.minimum_revision,
        previous_sha256=args.previous_sha256,
    )
    planner = partial(
        plan_next, catalog=catalog, key=load_signing_key(args.key, epoch=args.key_epoch)
    )
    outcome = _store().recompute(args.installation_id, planner, now=now)
    _print(schemas.outcome_record(outcome))
    return 0


def _show(args: argparse.Namespace) -> int:
    store = _store()
    now = domain.utc_now()
    plan = store.current_plan(args.installation_id, now=now)
    evaluation = store.last_evaluation(args.installation_id)
    active = tuple(
        w for w in store.load(args.installation_id).suppressions if w.starts_at <= now < w.ends_at
    )
    _print(
        {
            "enrollment": store.enrollment_status(args.installation_id),
            "plan": _plan_record(plan) if plan else None,
            "last_evaluation": (
                schemas.evaluation_json.dump_python(evaluation, mode="json") if evaluation else None
            ),
            "suppressions": schemas.suppressions_json.dump_python(active, mode="json"),
            "reports": [
                report.model_dump(mode="json") for report in store.reports(args.installation_id)
            ],
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

    from fdai_lifecycle_hub.api import DEFAULT_UI_DIST, create_app

    static_dir = args.ui if args.ui is not None else DEFAULT_UI_DIST
    uvicorn.run(
        create_app(_store(), static_dir=static_dir if static_dir.is_dir() else None),
        host=LOOPBACK,
        port=args.port,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

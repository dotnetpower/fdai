"""Open this installation's one Trial window at its anchored creation time.

A deployment runs this writer once per apply, after the state store is migrated and
with Core's state-store DSN. The activation time is the installation's recorded
creation time, never the time of the run, so a re-run, an upgrade, or a recreated
record cannot open a fresh window: an existing record is kept exactly as stored, and
a missing one is re-created at the original time. A record bound to another
installation is reported and left untouched.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from fdai.core.licensing.trial import TrialRecord
from fdai.delivery.persistence.postgres_licensing_trial import Connect, activate_trial_once

SCHEMA_VERSION = "fdai.trial-activation.v1"
EXIT_INVALID = 2
EXIT_REFUSED = 3
EXIT_UNAVAILABLE = 4

_BINDING = re.compile(r"[0-9a-f]{64}")
_STATEMENT_TIMEOUT_MS = 5_000
_CONNECT_TIMEOUT_S = 10


class TrialActivationInputError(ValueError):
    """The request is malformed, so no record was read or written."""


class TrialActivationRefusedError(RuntimeError):
    """A retained record belongs to another installation; it was not changed."""


def parse_activation_time(value: str) -> datetime:
    """Return an explicit UTC instant, refusing local or offset-shifted times."""

    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise TrialActivationInputError("activation time must be an ISO 8601 instant") from None
    if moment.tzinfo is None or moment.utcoffset() != timedelta(0):
        raise TrialActivationInputError("activation time must be explicit UTC")
    return moment.astimezone(UTC)


async def activate_installation_trial(
    *,
    connection: psycopg.AsyncConnection[Any],
    installation_binding: str,
    deployment_binding: str,
    activated_at: datetime,
    now: datetime,
) -> TrialRecord:
    """Commit the anchored window if absent and return the retained record."""

    for name, binding in (
        ("installation", installation_binding),
        ("deployment", deployment_binding),
    ):
        if _BINDING.fullmatch(binding) is None:
            raise TrialActivationInputError(f"{name} binding must be a lowercase SHA-256 digest")
    if activated_at.tzinfo is None or activated_at.utcoffset() != timedelta(0):
        raise TrialActivationInputError("activation time must be explicit UTC")
    if activated_at > now:
        raise TrialActivationInputError("activation time is in the future; no window was opened")
    async with connection.transaction():
        record = await activate_trial_once(
            connection=connection,
            set_statement_timeout=_set_statement_timeout,
            installation_binding=installation_binding,
            deployment_binding=deployment_binding,
            now=activated_at,
        )
    if (
        record.installation_binding != installation_binding
        or record.deployment_binding != deployment_binding
    ):
        raise TrialActivationRefusedError(
            "the retained Trial record belongs to another installation"
        )
    return record


async def _set_statement_timeout(connection: psycopg.AsyncConnection[Any]) -> None:
    await connection.execute(f"SET LOCAL statement_timeout = {_STATEMENT_TIMEOUT_MS}")


async def _activate(
    *,
    dsn: str,
    connect: Connect,
    installation_binding: str,
    deployment_binding: str,
    activated_at: datetime,
    now: datetime,
) -> TrialRecord:
    connection = await connect(dsn, connect_timeout=_CONNECT_TIMEOUT_S)
    async with connection:
        return await activate_installation_trial(
            connection=connection,
            installation_binding=installation_binding,
            deployment_binding=deployment_binding,
            activated_at=activated_at,
            now=now,
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m fdai.runtime.licensing_trial_activation",
        description=(
            "Open this installation's Trial window once, at its anchored creation time. "
            "Reads the state-store DSN from FDAI_STATE_STORE_DSN."
        ),
    )
    parser.add_argument("--installation-binding", required=True)
    parser.add_argument("--deployment-binding", required=True)
    parser.add_argument(
        "--activated-at",
        required=True,
        help="the installation's recorded creation time, as an ISO 8601 UTC instant",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] = os.environ,
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    connect: Connect | None = None,
) -> int:
    """Activate once and print one JSON receipt without credentials or endpoints."""

    args = _parser().parse_args(argv)
    dsn = environ.get("FDAI_STATE_STORE_DSN", "").strip()
    if not dsn:
        return _fail(EXIT_INVALID, "FDAI_STATE_STORE_DSN is not set")
    now = clock()
    try:
        record = asyncio.run(
            _activate(
                dsn=dsn,
                connect=connect or psycopg.AsyncConnection.connect,
                installation_binding=args.installation_binding,
                deployment_binding=args.deployment_binding,
                activated_at=parse_activation_time(args.activated_at),
                now=now,
            )
        )
    except TrialActivationInputError as error:
        return _fail(EXIT_INVALID, str(error))
    except TrialActivationRefusedError as error:
        return _fail(EXIT_REFUSED, str(error))
    except (OSError, psycopg.Error, RuntimeError, TimeoutError, ValueError) as error:
        return _fail(EXIT_UNAVAILABLE, f"Trial storage is unavailable ({type(error).__name__})")
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "outcome": "retained",
        "activated_at": record.activated_at.isoformat(),
        "expires_at": record.expires_at.isoformat(),
        "window_ended": now >= record.expires_at,
        "clock_blocked": record.clock_blocked,
    }
    print(json.dumps(receipt, ensure_ascii=True, separators=(",", ":"), sort_keys=True))
    return 0


def _fail(code: int, reason: str) -> int:
    receipt = {"schema_version": SCHEMA_VERSION, "outcome": "failed", "reason": reason}
    print(
        json.dumps(receipt, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
        file=sys.stderr,
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())

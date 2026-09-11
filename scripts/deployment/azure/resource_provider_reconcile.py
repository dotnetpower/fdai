#!/usr/bin/env python3
"""Inspect and idempotently register the Azure providers required by FDAI."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from genesis_subprocess import run_with_heartbeat

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

FOUNDATION_PROVIDERS = (
    "Microsoft.Authorization",
    "Microsoft.Compute",
    "Microsoft.DevTestLab",
    "Microsoft.EventGrid",
    "Microsoft.ManagedIdentity",
    "Microsoft.Network",
    "Microsoft.Resources",
    "Microsoft.Storage",
    "Microsoft.VirtualMachineImages",
)
APPLICATION_PROVIDERS = (
    "Microsoft.App",
    "Microsoft.Authorization",
    "Microsoft.CognitiveServices",
    "Microsoft.ContainerRegistry",
    "Microsoft.DBforPostgreSQL",
    "Microsoft.EventGrid",
    "Microsoft.EventHub",
    "Microsoft.Insights",
    "Microsoft.KeyVault",
    "Microsoft.ManagedIdentity",
    "Microsoft.Network",
    "Microsoft.OperationalInsights",
    "Microsoft.Resources",
    "Microsoft.Storage",
)
PROVIDER_PROFILES = {
    "foundation": FOUNDATION_PROVIDERS,
    "application": APPLICATION_PROVIDERS,
    "complete": tuple(dict.fromkeys((*FOUNDATION_PROVIDERS, *APPLICATION_PROVIDERS))),
}
_GUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_MISSING_STATES = frozenset({"notregistered", "unregistered"})
_PENDING_STATES = frozenset({"registering"})


class ProviderReconcileError(RuntimeError):
    """Report a bounded provider inspection or registration failure."""

    def __init__(self, message: str, *, mutation_performed: bool = False) -> None:
        super().__init__(message)
        self.mutation_performed = mutation_performed


class CommandRunner(Protocol):
    """Run one bounded Azure CLI command."""

    def __call__(
        self, arguments: Sequence[str], timeout_seconds: float
    ) -> subprocess.CompletedProcess[str]:
        """Return the completed command without raising for its exit code."""


ProgressCallback = Callable[[str, int, int], None]


@dataclass(frozen=True, slots=True)
class ProviderReport:
    """Sanitized provider reconciliation result for one exact target."""

    profile: str
    required: tuple[str, ...]
    registered: tuple[str, ...]
    missing: tuple[str, ...]
    requested: tuple[str, ...]
    mutation_performed: bool

    @property
    def state(self) -> str:
        """Return ready only when every required provider is registered."""

        return "ready" if not self.missing else "review"

    def to_mapping(self) -> dict[str, object]:
        """Return stable machine output without target identifiers."""

        return {
            "schema_version": "fdai.azure-resource-provider-reconcile.v1",
            "state": self.state,
            "profile": self.profile,
            "required_count": len(self.required),
            "registered_count": len(self.registered),
            "missing": list(self.missing),
            "registration_requested": list(self.requested),
            "mutation_performed": self.mutation_performed,
            "rollback": "retain-registration",
        }


def run_azure_cli(
    arguments: Sequence[str], timeout_seconds: float
) -> subprocess.CompletedProcess[str]:
    """Run Azure CLI with bounded output and no interactive input."""

    return run_with_heartbeat(
        ("az", *arguments),
        cwd=_REPOSITORY_ROOT,
        capture_output=True,
        timeout=timeout_seconds,
    )


def reconcile_resource_providers(
    *,
    subscription_id: str,
    profile: str,
    apply: bool,
    run: CommandRunner = run_azure_cli,
    timeout_seconds: int = 900,
    poll_seconds: float = 5.0,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    progress: ProgressCallback | None = None,
) -> ProviderReport:
    """Inspect providers and optionally register only missing namespaces.

    Registration requests are issued once, then observed under one cumulative
    deadline. Existing registrations are never removed automatically.
    """

    if _GUID.fullmatch(subscription_id) is None:
        raise ValueError("subscription_id must be an Azure UUID")
    if profile not in PROVIDER_PROFILES:
        raise ValueError("provider profile is unsupported")
    if not 30 <= timeout_seconds <= 1800:
        raise ValueError("provider reconciliation timeout must be from 30 through 1800 seconds")
    if not 0 < poll_seconds <= 30:
        raise ValueError("provider reconciliation poll interval must be within 30 seconds")

    required = PROVIDER_PROFILES[profile]
    deadline = monotonic() + timeout_seconds
    try:
        states = _inspect_all(subscription_id, required, run, deadline, monotonic)
    except subprocess.TimeoutExpired as exc:
        raise ProviderReconcileError("Azure resource provider inspection timed out") from exc
    missing = tuple(namespace for namespace in required if states[namespace] != "registered")
    ambiguous = tuple(
        namespace
        for namespace in missing
        if states[namespace] not in _MISSING_STATES | _PENDING_STATES
    )
    if ambiguous:
        raise ProviderReconcileError("provider registration state is indeterminate")
    if not apply or not missing:
        return _report(profile, required, states, (), False)

    requested: list[str] = []
    for index, namespace in enumerate(missing, start=1):
        if states[namespace] in _PENDING_STATES:
            continue
        remaining_seconds = deadline - monotonic()
        if remaining_seconds <= 0:
            raise ProviderReconcileError(
                "Azure resource provider registration did not converge",
                mutation_performed=bool(requested),
            )
        if progress is not None:
            progress(namespace, index, len(missing))
        try:
            completed = run(
                (
                    "provider",
                    "register",
                    "--subscription",
                    subscription_id,
                    "--namespace",
                    namespace,
                    "--output",
                    "none",
                    "--only-show-errors",
                ),
                min(60, remaining_seconds),
            )
        except subprocess.TimeoutExpired as exc:
            raise ProviderReconcileError(
                "Azure resource provider registration request timed out",
                mutation_performed=True,
            ) from exc
        if completed.returncode != 0:
            raise ProviderReconcileError(
                "Azure resource provider registration request failed",
                mutation_performed=True,
            )
        requested.append(namespace)

    last_registered = -1
    while True:
        try:
            states = _inspect_all(subscription_id, required, run, deadline, monotonic)
        except ProviderReconcileError as exc:
            raise ProviderReconcileError(str(exc), mutation_performed=bool(requested)) from exc
        except subprocess.TimeoutExpired as exc:
            raise ProviderReconcileError(
                "Azure resource provider registration readback timed out",
                mutation_performed=bool(requested),
            ) from exc
        remaining = tuple(namespace for namespace in required if states[namespace] != "registered")
        registered_count = len(required) - len(remaining)
        if progress is not None and registered_count != last_registered:
            progress("readback", registered_count, len(required))
            last_registered = registered_count
        if not remaining:
            return _report(profile, required, states, tuple(requested), bool(requested))
        if any(
            states[namespace] not in _MISSING_STATES | _PENDING_STATES for namespace in remaining
        ):
            raise ProviderReconcileError(
                "provider registration readback is indeterminate",
                mutation_performed=bool(requested),
            )
        if monotonic() >= deadline:
            raise ProviderReconcileError(
                "Azure resource provider registration did not converge",
                mutation_performed=bool(requested),
            )
        remaining_seconds = deadline - monotonic()
        if remaining_seconds <= 0:
            raise ProviderReconcileError(
                "Azure resource provider registration did not converge",
                mutation_performed=bool(requested),
            )
        sleep(min(poll_seconds, remaining_seconds))


def _inspect_all(
    subscription_id: str,
    required: tuple[str, ...],
    run: CommandRunner,
    deadline: float,
    monotonic: Callable[[], float],
) -> dict[str, str]:
    states: dict[str, str] = {}
    for namespace in required:
        remaining_seconds = deadline - monotonic()
        if remaining_seconds <= 0:
            raise subprocess.TimeoutExpired("az provider show", 0)
        completed = run(
            (
                "provider",
                "show",
                "--subscription",
                subscription_id,
                "--namespace",
                namespace,
                "--query",
                "registrationState",
                "--output",
                "tsv",
                "--only-show-errors",
            ),
            min(30, remaining_seconds),
        )
        if completed.returncode != 0:
            raise ProviderReconcileError("Azure resource provider inspection failed")
        state = completed.stdout.strip().casefold()
        if state not in {"registered", *_MISSING_STATES, *_PENDING_STATES}:
            state = "indeterminate"
        states[namespace] = state
    return states


def _report(
    profile: str,
    required: tuple[str, ...],
    states: dict[str, str],
    requested: tuple[str, ...],
    mutation_performed: bool,
) -> ProviderReport:
    registered = tuple(namespace for namespace in required if states[namespace] == "registered")
    missing = tuple(namespace for namespace in required if states[namespace] != "registered")
    return ProviderReport(
        profile=profile,
        required=required,
        registered=registered,
        missing=missing,
        requested=requested,
        mutation_performed=mutation_performed,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription-id", required=True)
    parser.add_argument("--profile", choices=tuple(PROVIDER_PROFILES), default="complete")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--output", choices=("text", "json"), default="text")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run provider inspection or explicit idempotent registration."""

    args = _parser().parse_args(argv)
    try:
        report = reconcile_resource_providers(
            subscription_id=args.subscription_id,
            profile=args.profile,
            apply=args.apply,
            timeout_seconds=args.timeout_seconds,
            progress=lambda namespace, completed, total: print(
                f"provider progress: {completed}/{total} {namespace}", file=sys.stderr
            ),
        )
    except (ProviderReconcileError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"resource-provider reconciliation failed: {exc}", file=sys.stderr)
        return 4
    if args.output == "json":
        print(json.dumps(report.to_mapping(), sort_keys=True, separators=(",", ":")))
    else:
        print(
            f"providers {len(report.registered)}/{len(report.required)} registered; "
            f"state={report.state}"
        )
        for namespace in report.missing:
            print(f"  registration required: {namespace}")
    return 0 if report.state == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Bounded TLS egress preflight for the VNet-integrated deployment runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import socket
import ssl
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Final

_HOST = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,63}$"
)
_MAX_HOSTS: Final[int] = 32
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 5.0

Connector = Callable[[str, float], None]


class EgressPreflightError(RuntimeError):
    """The runner egress preflight is invalid or incomplete."""


def run_checks(
    hosts: object,
    *,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    connector: Connector | None = None,
) -> dict[str, object]:
    """Return hashed TLS reachability evidence or raise on any failed host."""
    if (
        not isinstance(hosts, list)
        or not hosts
        or len(hosts) > _MAX_HOSTS
        or not all(isinstance(host, str) and _HOST.fullmatch(host) for host in hosts)
    ):
        raise EgressPreflightError("egress hosts MUST be 1-32 bounded DNS names")
    if timeout_seconds <= 0 or timeout_seconds > 30:
        raise EgressPreflightError("timeout_seconds MUST be in (0, 30]")
    connect = connector or _tls_connect
    refs: list[str] = []
    for host in sorted(set(hosts)):
        try:
            connect(host, timeout_seconds)
        except (OSError, ssl.SSLError) as exc:
            reference = _host_ref(host)
            raise EgressPreflightError(
                f"required TLS egress endpoint is unreachable ({reference})"
            ) from exc
        refs.append(_host_ref(host))
    return {
        "schema_version": "fdai.runner-egress-preflight.v1",
        "complete": True,
        "checked_count": len(refs),
        "endpoint_refs": refs,
    }


def _tls_connect(host: str, timeout_seconds: float) -> None:
    context = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=timeout_seconds) as sock:
        with context.wrap_socket(sock, server_hostname=host):
            return


def _host_ref(host: str) -> str:
    return f"sha256:{hashlib.sha256(host.casefold().encode('utf-8')).hexdigest()[:16]}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=_DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)
    try:
        hosts = json.loads(args.manifest.read_text(encoding="utf-8"))
        evidence = run_checks(hosts, timeout_seconds=args.timeout_seconds)
        args.output.write_text(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    except (OSError, json.JSONDecodeError, EgressPreflightError) as exc:
        print(f"runner egress preflight failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

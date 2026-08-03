#!/usr/bin/env python3
"""Start or resume one catalog Workflow through the shadow command API."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEFAULT_API_URL = "http://127.0.0.1:8000"
DEFAULT_AUTH_ENV = "FDAI_API_TOKEN"
PROCESS_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Start a catalog Workflow or resume an exact Process.",
    )
    parser.add_argument("workflow", nargs="?", help="Catalog Workflow name for a new run.")
    parser.add_argument("--target", help="Target resource id or scope for a new run.")
    parser.add_argument(
        "--resume-process-id",
        help="Resume one durable Process without resupplying its workflow inputs.",
    )
    parser.add_argument(
        "--cancel-process-id",
        help="Cancel one durable Process at its current safe boundary.",
    )
    parser.add_argument(
        "--retry-process-id",
        help="Retry one effect-free failed or approval-timed-out Process.",
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("FDAI_OPERATOR_API_URL", DEFAULT_API_URL),
        help="FDAI API base URL (default: %(default)s).",
    )
    parser.add_argument(
        "--trigger-ts",
        help="RFC 3339 trigger timestamp for a new run.",
    )
    parser.add_argument(
        "--context",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Parameter-substitution context entry for a new run.",
    )
    parser.add_argument("--correlation-id", help="Optional correlation id.")
    parser.add_argument(
        "--token-env",
        default=DEFAULT_AUTH_ENV,
        help="Environment variable containing the bearer token (default: %(default)s).",
    )
    return parser


def _context(entries: list[str], parser: argparse.ArgumentParser) -> dict[str, str]:
    context: dict[str, str] = {}
    for entry in entries:
        key, separator, value = entry.partition("=")
        if not separator or not key:
            parser.error(f"--context expects KEY=VALUE, got {entry!r}")
        context[key] = value
    return context


def _request(args: argparse.Namespace, parser: argparse.ArgumentParser) -> Request:
    api_url = args.api_url.rstrip("/")
    parsed = urlparse(api_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        parser.error("--api-url MUST be an absolute http or https URL")
    token = os.environ.get(args.token_env, "").strip()
    if token and parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost"}:
        parser.error("refusing to send a bearer token over non-local HTTP")
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    process_commands = tuple(
        (value, command)
        for value, command in (
            (args.resume_process_id, "resume"),
            (args.cancel_process_id, "cancel"),
            (args.retry_process_id, "retry"),
        )
        if value is not None
    )
    if len(process_commands) > 1:
        parser.error("Process resume, cancel, and retry commands are mutually exclusive")
    process_command = process_commands[0] if process_commands else None
    if process_command is not None:
        raw_process_id, command = process_command
        process_id = raw_process_id.strip()
        if not PROCESS_ID_PATTERN.fullmatch(process_id):
            parser.error(f"--{command}-process-id MUST be a URL-safe Process id")
        if any(
            (
                args.workflow,
                args.target,
                args.trigger_ts,
                args.context,
                args.correlation_id,
            )
        ):
            parser.error(f"--{command}-process-id cannot be combined with new-run inputs")
        return Request(  # noqa: S310 - scheme and authority validated above
            f"{api_url}/workflows/{process_id}/{command}",
            headers=headers,
            method="POST",
        )
    if not args.workflow or not args.target:
        parser.error("a new run requires WORKFLOW and --target")
    payload = {
        "workflow": args.workflow,
        "target_resource_id": args.target,
        "trigger_ts": args.trigger_ts or datetime.now(tz=UTC).isoformat(),
        "context": _context(args.context, parser),
    }
    if args.correlation_id:
        payload["correlation_id"] = args.correlation_id
    headers["Content-Type"] = "application/json"
    return Request(  # noqa: S310 - scheme and authority validated above
        f"{api_url}/workflows/run",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    request = _request(args, parser)
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310 - URL validated above
            result = json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"workflow command failed ({exc.code}): {detail}", file=sys.stderr)
        return 1
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"workflow command failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

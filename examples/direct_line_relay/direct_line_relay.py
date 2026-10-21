#!/usr/bin/env python3
"""Run a bounded Direct Line-compatible relay for local FDAI validation."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path
from typing import Final, TextIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

_MAX_ACTIVITY_BYTES: Final[int] = 48 * 1024
_MAX_RECEIPT_BYTES: Final[int] = 4096
_IDEMPOTENCY_KEY: Final = re.compile(r"^[0-9a-f]{64}$")
_BOUNDED_ID: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")
_BEARER_SECRET: Final = re.compile(r"^[\x21-\x7e]{1,8192}$")
_TRUST_TIERS: Final[frozenset[str]] = frozenset({"a2_operational_alert", "a4_digest"})
_ACTIVITY_DIGEST_PREFIX: Final[str] = "activity-sha256:"


class RelayRequestError(ValueError):
    """A received activity violated the bounded read-only relay contract."""


@dataclass(frozen=True, slots=True)
class RelayConfig:
    host: str
    port: int
    conversation_id: str
    receipt_url: str
    state_file: Path
    callback_timeout_seconds: float = 5.0
    once: bool = False

    def __post_init__(self) -> None:
        if not _is_loopback_host(self.host):
            raise ValueError("the example relay host MUST resolve to loopback")
        if not 0 <= self.port <= 65535:
            raise ValueError("relay port MUST be in [0, 65535]")
        if _BOUNDED_ID.fullmatch(self.conversation_id) is None:
            raise ValueError("conversation id MUST be a bounded ASCII identifier")
        _validate_receipt_url(self.receipt_url)
        if self.callback_timeout_seconds <= 0:
            raise ValueError("callback timeout MUST be positive")


@dataclass(frozen=True, slots=True)
class RelayActivity:
    idempotency_key: str
    audit_id: str
    channel_id: str
    category: str
    trust_tier: str


class RelayState:
    """Persist accepted activity identities before publication callbacks."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._records = self._load()

    def accept(
        self,
        activity: RelayActivity,
        *,
        conversation_id: str,
    ) -> tuple[str, bool, bool]:
        with self._lock:
            existing = self._records.get(activity.idempotency_key)
            if existing is not None:
                activity_id = existing.get("activity_id")
                if not isinstance(activity_id, str):
                    raise RelayRequestError("stored activity identifier is invalid")
                if not _same_activity(existing, activity):
                    raise RelayRequestError(
                        "idempotency key conflicts with a previously accepted activity"
                    )
                return activity_id, False, existing.get("receipt_status") != "published"

            activity_id = f"{conversation_id}|{activity.idempotency_key[:16]}"
            self._records[activity.idempotency_key] = _record(activity, activity_id)
            self._write()
            return activity_id, True, True

    def mark_receipt_published(self, idempotency_key: str) -> None:
        with self._lock:
            record = self._records.get(idempotency_key)
            if record is None:
                raise RuntimeError("accepted activity disappeared before receipt completion")
            record["receipt_status"] = "published"
            self._write()

    def _load(self) -> dict[str, dict[str, object]]:
        if not self._path.exists():
            return {}
        value = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("relay state MUST be a JSON object")
        records: dict[str, dict[str, object]] = {}
        for key, item in value.items():
            if _IDEMPOTENCY_KEY.fullmatch(key) is None or not isinstance(item, dict):
                raise ValueError("relay state contains an invalid record")
            required = {
                "activity_id",
                "audit_id",
                "category",
                "channel_id",
                "idempotency_key",
                "receipt_status",
                "trust_tier",
            }
            if (
                set(item) != required
                or item.get("idempotency_key") != key
                or item.get("receipt_status") not in {"pending", "published"}
            ):
                raise ValueError("relay state contains an invalid record")
            records[key] = dict(item)
        return records

    def _write(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temporary.write_text(
            json.dumps(self._records, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self._path)


class DirectLineRelayServer(ThreadingHTTPServer):
    """Loopback-only server carrying injected secrets outside CLI arguments."""

    daemon_threads = True

    def __init__(
        self,
        config: RelayConfig,
        *,
        bearer_secret: str,
        receipt_secret: str,
        output: TextIO,
    ) -> None:
        if _BEARER_SECRET.fullmatch(bearer_secret) is None:
            raise ValueError("relay bearer secret MUST be non-empty printable ASCII")
        if not receipt_secret:
            raise ValueError("receipt secret MUST be non-empty")
        self.config = config
        self.bearer_secret = bearer_secret
        self.receipt_secret = receipt_secret
        self.output = output
        self.state = RelayState(config.state_file)
        self.callback_failed = threading.Event()
        super().__init__((config.host, config.port), DirectLineRelayHandler)

    @property
    def activities_path(self) -> str:
        return f"/v3/directline/conversations/{self.config.conversation_id}/activities"

    def emit(self, event: str, **fields: object) -> None:
        print(
            json.dumps({"event": event, **fields}, sort_keys=True, separators=(",", ":")),
            file=self.output,
            flush=True,
        )

    def publish_receipt(self, activity: RelayActivity, activity_id: str) -> None:
        provider_message_id = (
            f"{_ACTIVITY_DIGEST_PREFIX}{hashlib.sha256(activity_id.encode('utf-8')).hexdigest()}"
        )
        body = json.dumps(
            {
                "audit_id": activity.audit_id,
                "channel_id": activity.channel_id,
                "publication_result": "published",
                "provider_message_id": provider_message_id,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        if len(body) > _MAX_RECEIPT_BYTES:
            raise RuntimeError("receipt body exceeds the bounded size")
        timestamp = datetime.now(tz=UTC).isoformat()
        signature = hmac.new(
            self.receipt_secret.encode("utf-8"),
            timestamp.encode("utf-8") + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        request = Request(  # noqa: S310 - config accepts only HTTPS or loopback HTTP.
            self.config.receipt_url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-FDAI-Timestamp": timestamp,
                "X-FDAI-Signature": f"sha256={signature}",
            },
        )
        try:
            with urlopen(  # noqa: S310 - the validated request can't use another scheme.
                request,
                timeout=self.config.callback_timeout_seconds,
            ) as response:
                if response.status != HTTPStatus.ACCEPTED:
                    raise RuntimeError(
                        f"receipt ingress returned unexpected HTTP {response.status}"
                    )
        except HTTPError as exc:
            raise RuntimeError(f"receipt ingress returned unexpected HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(
                f"receipt ingress connection failed: {type(exc.reason).__name__}"
            ) from exc
        self.state.mark_receipt_published(activity.idempotency_key)
        self.emit(
            "receipt_published",
            audit_id=activity.audit_id,
            channel_id=activity.channel_id,
            provider_message_id=provider_message_id,
        )


class DirectLineRelayHandler(BaseHTTPRequestHandler):
    """Accept one bounded read-only activity and acknowledge it before callback."""

    server: DirectLineRelayServer

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        if self.path != self.server.activities_path:
            self._reply(HTTPStatus.NOT_FOUND, {"error": "route_not_found"})
            return
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {self.server.bearer_secret}"
        if not hmac.compare_digest(supplied, expected):
            self._reply(HTTPStatus.UNAUTHORIZED, {"error": "invalid_credential"})
            return
        try:
            body = self._read_body()
            activity = _parse_activity(body)
            activity_id, created, receipt_required = self.server.state.accept(
                activity,
                conversation_id=self.server.config.conversation_id,
            )
        except RelayRequestError as exc:
            self._reply(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        except (OSError, ValueError) as exc:
            self.server.emit("relay_state_failed", error_type=type(exc).__name__)
            self._reply(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "relay_state_failed"})
            return

        self._reply(HTTPStatus.OK, {"id": activity_id})
        self.server.emit(
            "activity_accepted",
            audit_id=activity.audit_id,
            channel_id=activity.channel_id,
            duplicate=not created,
            idempotency_key=activity.idempotency_key,
        )
        if receipt_required:
            threading.Thread(
                target=self._publish_after_acceptance,
                args=(activity, activity_id),
                daemon=True,
            ).start()
        elif self.server.config.once:
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    def _publish_after_acceptance(
        self,
        activity: RelayActivity,
        activity_id: str,
    ) -> None:
        try:
            self.server.publish_receipt(activity, activity_id)
        except (OSError, RuntimeError) as exc:
            self.server.callback_failed.set()
            self.server.emit("receipt_failed", error_type=type(exc).__name__)
        finally:
            if self.server.config.once:
                self.server.shutdown()

    def _read_body(self) -> bytes:
        raw_length = self.headers.get("Content-Length", "")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise RelayRequestError("content length is invalid") from exc
        if not 1 <= length <= _MAX_ACTIVITY_BYTES:
            raise RelayRequestError("activity body exceeds the bounded size")
        return self.rfile.read(length)

    def _reply(self, status: HTTPStatus, body: dict[str, object]) -> None:
        encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


def create_server(
    config: RelayConfig,
    *,
    bearer_secret: str,
    receipt_secret: str,
    output: TextIO = sys.stdout,
) -> DirectLineRelayServer:
    """Create the loopback relay without starting its serving loop."""

    return DirectLineRelayServer(
        config,
        bearer_secret=bearer_secret,
        receipt_secret=receipt_secret,
        output=output,
    )


def _parse_activity(body: bytes) -> RelayActivity:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RelayRequestError("activity body is not valid JSON") from exc
    if not isinstance(value, dict):
        raise RelayRequestError("activity body MUST be an object")
    if value.get("type") != "message" or value.get("textFormat") != "markdown":
        raise RelayRequestError("activity MUST be one Markdown message")
    if {"attachments", "suggestedActions", "value"} & set(value):
        raise RelayRequestError("activity MUST remain read-only")
    channel_data = value.get("channelData")
    fdai = channel_data.get("fdai") if isinstance(channel_data, dict) else None
    if not isinstance(fdai, dict) or fdai.get("read_only") is not True:
        raise RelayRequestError("activity has no read-only FDAI record")
    idempotency_key = _required_text(fdai, "idempotency_key")
    if _IDEMPOTENCY_KEY.fullmatch(idempotency_key) is None:
        raise RelayRequestError("activity idempotency key is invalid")
    audit_id = _required_text(fdai, "audit_id")
    channel_id = _required_text(fdai, "channel_id")
    category = _required_text(fdai, "category")
    trust_tier = _required_text(fdai, "trust_tier")
    if trust_tier not in _TRUST_TIERS:
        raise RelayRequestError("activity trust tier is not supported")
    return RelayActivity(
        idempotency_key=idempotency_key,
        audit_id=audit_id,
        channel_id=channel_id,
        category=category,
        trust_tier=trust_tier,
    )


def _required_text(value: dict[str, object], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item or len(item) > 256:
        raise RelayRequestError(f"activity {field} is invalid")
    return item


def _record(activity: RelayActivity, activity_id: str) -> dict[str, object]:
    return {
        "activity_id": activity_id,
        "audit_id": activity.audit_id,
        "category": activity.category,
        "channel_id": activity.channel_id,
        "idempotency_key": activity.idempotency_key,
        "receipt_status": "pending",
        "trust_tier": activity.trust_tier,
    }


def _same_activity(record: dict[str, object], activity: RelayActivity) -> bool:
    return all(
        record.get(field) == expected
        for field, expected in (
            ("audit_id", activity.audit_id),
            ("category", activity.category),
            ("channel_id", activity.channel_id),
            ("idempotency_key", activity.idempotency_key),
            ("trust_tier", activity.trust_tier),
        )
    )


def _is_loopback_host(hostname: str) -> bool:
    if hostname.casefold() == "localhost":
        return True
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False


def _validate_receipt_url(value: str) -> None:
    parts = urlsplit(value)
    if not parts.hostname or parts.username is not None or parts.password is not None:
        raise ValueError("receipt URL MUST be an absolute URL without credentials")
    if parts.scheme == "https":
        return
    if parts.scheme == "http" and _is_loopback_host(parts.hostname):
        return
    raise ValueError("receipt URL MUST use HTTPS except on loopback")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a local Direct Line-compatible FDAI notification relay."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--conversation-id", default="example-conversation")
    parser.add_argument("--receipt-url", required=True)
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument(
        "--bearer-secret-env",
        default="FDAI_EXAMPLE_DIRECT_LINE_SECRET",
    )
    parser.add_argument(
        "--receipt-secret-env",
        default="FDAI_NOTIFICATION_RECEIPT_SECRET",
    )
    parser.add_argument("--once", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    bearer_secret = os.environ.get(args.bearer_secret_env, "")
    receipt_secret = os.environ.get(args.receipt_secret_env, "")
    if not bearer_secret or not receipt_secret:
        print(
            "relay and receipt secrets MUST be provided through the named environment variables",
            file=sys.stderr,
        )
        return 2
    try:
        config = RelayConfig(
            host=args.host,
            port=args.port,
            conversation_id=args.conversation_id,
            receipt_url=args.receipt_url,
            state_file=args.state_file,
            once=args.once,
        )
        server = create_server(
            config,
            bearer_secret=bearer_secret,
            receipt_secret=receipt_secret,
        )
    except (OSError, ValueError) as exc:
        print(f"relay startup failed: {exc}", file=sys.stderr)
        return 2
    with server:
        host, port = server.server_address[:2]
        server.emit(
            "listening",
            endpoint=f"http://{host}:{port}",
            conversation_id=config.conversation_id,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            return 130
    return 1 if server.callback_failed.is_set() else 0


if __name__ == "__main__":
    raise SystemExit(main())

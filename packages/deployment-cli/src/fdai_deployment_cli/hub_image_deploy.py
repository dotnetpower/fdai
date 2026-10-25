"""Connected image-bootstrap inputs and public, self-reported request intake."""

from __future__ import annotations

import hashlib
import http.client
import re
import ssl
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest, load_json_object
from fdai_deployment_cli.hub_image_trust import (
    MAX_EXPORT_BYTES,
    MAX_SELECTION_BYTES,
    HubImageSelection,
    load_selection,
    public_key,
    selection_bytes,
    validate_channel,
    verify_export,
)
from fdai_deployment_cli.private_output import read_private_bytes, write_private_bytes
from fdai_deployment_cli.source_input import inspect_source

DEFAULT_HUB_URL = "https://hub.msfdai.com"


def require_retained_hub_recovery(
    selection: HubImageSelection, *, work_dir: Path, target_binding: str
) -> None:
    """Check the original mode and human target before recovery can advance any effect."""
    intent = load_json_object(
        read_private_bytes(work_dir / "source-intent.json", max_bytes=65_536),
        label="retained Hub support intent",
        strict=True,
    )
    marker = load_json_object(
        read_private_bytes(work_dir / "foundation/source-genesis.json", max_bytes=65_536),
        label="retained Hub Foundation binding",
        strict=True,
    )
    digest = marker.pop("receipt_digest", None)
    if (
        intent.get("hub_selection_digest") != selection.digest
        or intent.get("artifact_source") != "hub-signed-images"
        or canonical_digest(marker) != digest
        or marker.get("target_binding") != target_binding
        or marker.get("source_commit") != selection.source_commit
    ):
        raise ValueError("Hub recovery mode, Release or selected Azure target drifted")


def validate_hub_url(url: str) -> str:
    parsed = urlsplit(url)
    if (
        len(url) > 512
        or parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or re.fullmatch(r"https://[a-z0-9][a-z0-9.-]*(?::[1-9][0-9]{0,4})?/?", url) is None
    ):
        raise ValueError("Hub URL must be one explicit HTTPS origin without credentials or path")
    if parsed.port is not None and parsed.port > 65535:
        raise ValueError("Hub HTTPS port is invalid")
    return url.rstrip("/")


def hub_request(
    hub_url: str, path: str, *, body: bytes | None = None
) -> tuple[int, dict[str, str], bytes]:
    """One bounded TLS request, without proxies, redirects, tokens or automatic retries."""
    origin = urlsplit(validate_hub_url(hub_url))
    assert origin.hostname is not None
    if path not in {"/v1/catalog/export", "/v1/deployment-requests"}:
        raise ValueError("Hub request path is not allowed")
    limit = MAX_EXPORT_BYTES if body is None else 16_384
    connection = http.client.HTTPSConnection(
        origin.hostname, origin.port or 443, timeout=15, context=ssl.create_default_context()
    )
    deadline = time.monotonic() + 30
    try:
        headers = {"Accept": "application/json", "Connection": "close"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        connection.request("GET" if body is None else "POST", path, body=body, headers=headers)
        response = connection.getresponse()
        if response.status not in ({200} if body is None else {200, 201}):
            raise ValueError(
                f"Hub request was refused (HTTP {response.status}); redirects and "
                "source-build fallback are disabled"
            )
        if response.getheader("Content-Encoding", "identity") != "identity":
            raise ValueError("Hub response encoding is unsupported")
        length = response.getheader("Content-Length")
        if length is not None and (not length.isdecimal() or int(length) > limit):
            raise ValueError("Hub response exceeds its size bound")
        result = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError("Hub request deadline exceeded")
            if connection.sock is not None:
                connection.sock.settimeout(min(15, remaining))
            chunk = response.read1(min(65_536, limit + 1 - len(result)))
            if not chunk:
                break
            result.extend(chunk)
            if len(result) > limit:
                raise ValueError("Hub response exceeds its size bound")
        if length is not None and len(result) != int(length):
            raise ValueError("Hub response body is incomplete")
        signature_headers: dict[str, str] = {}
        for name in ("X-FDAI-Export-Signature", "X-FDAI-Export-Key-Id"):
            values = response.headers.get_all(name, [])
            if len(values) > 1:
                raise ValueError("Hub response has ambiguous signature headers")
            signature_headers[name.lower()] = values[0] if values else ""
        return response.status, signature_headers, bytes(result)
    except (TimeoutError, OSError, http.client.HTTPException) as error:
        raise ValueError(
            "Hub network request failed; preserve retained inputs and inspect any pending "
            "deployment request before retrying. No automatic retry or source-build fallback."
        ) from error
    finally:
        connection.close()


def prepare_hub_selection(
    *,
    source_root: Path,
    work_dir: Path,
    public_key_path: Path,
    hub_url: str = DEFAULT_HUB_URL,
    channel: str = "RELEASE",
    release_id: str | None = None,
) -> HubImageSelection:
    """Verify before any Azure call and seal a selection that reruns cannot retarget."""
    hub_url = validate_hub_url(hub_url)
    validate_channel(channel)
    with public_key_path.open("rb") as stream:
        pem = stream.read(4097)
    public_key(pem)
    source = inspect_source(source_root)
    if work_dir.resolve().is_relative_to(source.root):
        raise ValueError("Hub work directory must be outside the selected checkout")
    inputs = work_dir / "hub-images"
    path = inputs / "selection.json"
    previous = None
    if path.exists():
        raw = read_private_bytes(path, max_bytes=MAX_SELECTION_BYTES)
        previous = load_selection(path, hashlib.sha256(raw).hexdigest())
        if (
            previous.document["hub_url"] != hub_url
            or previous.document["channel"] != channel
            or previous.document["public_key"] != pem.decode("ascii")
            or release_id not in {None, previous.release_id}
        ):
            raise ValueError(
                "Hub selection mode, origin, channel, key or Release drift; use a new work directory"
            )
        release_id = previous.release_id
    elif work_dir.exists() and any(work_dir.iterdir()):
        raise ValueError("Hub images cannot adopt source, kit, or partial work state")
    _, headers, raw = hub_request(hub_url, "/v1/catalog/export")
    verified = verify_export(
        raw,
        signature=headers["x-fdai-export-signature"],
        export_key_id=headers["x-fdai-export-key-id"],
        trusted_pem=pem,
        channel=channel,
        release_id=release_id,
        minimum_revision=previous.document["catalog_revision"] if previous else 0,
        previous_digest=previous.document["catalog_digest"] if previous else None,
    )
    if source.commit != verified["source_commit"]:
        raise ValueError(
            "Hub Release source_commit differs from checkout migrations and Console. "
            f"Check out the exact approved commit {verified['source_commit']} and rerun; "
            "no Azure deployment effect or source-build fallback was attempted."
        )
    selected = selection_bytes(
        raw=raw,
        signature=headers["x-fdai-export-signature"],
        export_key_id=headers["x-fdai-export-key-id"],
        pem=pem,
        hub_url=hub_url,
        channel=channel,
        verified=verified,
    )
    digest = hashlib.sha256(selected).hexdigest()
    if previous is not None:
        if digest != previous.digest:
            raise ValueError(
                "Hub immutable catalog selection changed; preserve this run and use a new work directory"
            )
        return previous
    inputs.mkdir(mode=0o700, parents=True, exist_ok=True)
    work_dir.chmod(0o700)
    write_private_bytes(path, selected)
    return load_selection(path, digest)


def record_deployment_request(
    selection: HubImageSelection, *, subscription_id: str, region: str
) -> dict[str, object]:
    """Record self-reported metadata once; uncertain mutations remain an explicit stop."""
    subscription_id = str(UUID(subscription_id))
    if re.fullmatch(r"[a-z][a-z0-9]{0,63}", region) is None:
        raise ValueError("Hub deployment request region is invalid")
    payload = {
        "subscription_id": subscription_id,
        "release_id": selection.release_id,
        "channel": selection.document["channel"],
        "region": region,
        "source_commit": selection.source_commit,
        "catalog_digest": selection.document["catalog_digest"],
    }
    payload["request_id"] = hashlib.sha256(canonical_bytes(payload)).hexdigest()
    root = selection.path.parent
    pending, receipt = root / "request-pending.json", root / "request-receipt.json"
    if pending.exists():
        retained = load_json_object(
            read_private_bytes(pending, max_bytes=16_384), label="Hub request", strict=True
        )
        if retained != payload:
            raise ValueError("Hub deployment request target or inputs drifted")
        if not receipt.exists():
            raise ValueError(
                "Hub deployment request has an uncertain outcome. Inspect its retained "
                "request_id with a Hub operator; do not automatically resubmit."
            )
        result = load_json_object(
            read_private_bytes(receipt, max_bytes=16_384), label="Hub request receipt", strict=True
        )
    else:
        if receipt.exists():
            raise ValueError("Hub request pending evidence is missing")
        write_private_bytes(pending, canonical_bytes(payload))
        _, _, raw = hub_request(
            selection.document["hub_url"], "/v1/deployment-requests", body=canonical_bytes(payload)
        )
        result = load_json_object(raw, label="Hub request response", max_bytes=16_384, strict=True)
    if (
        set(result) != set(payload) | {"status", "trust", "recorded_at"}
        or any(result.get(name) != value for name, value in payload.items())
        or result["status"] != "requested"
        or result["trust"] != "self-reported"
        or not isinstance(result["recorded_at"], str)
        or datetime.fromisoformat(result["recorded_at"]).tzinfo is None
    ):
        raise ValueError("Hub request receipt differs; deployment is stopped")
    if not receipt.exists():
        write_private_bytes(receipt, canonical_bytes(result))
    return result

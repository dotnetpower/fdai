"""GitOpsPrAdapter - HTTP-level round-trip via httpx.MockTransport.

Exercises the wire contract the P2 rollout will rely on:

- Bearer auth on every request.
- Idempotency probe returns the existing PR without any writes.
- Full publish flow: base-sha lookup → branch create → contents PUT →
  draft PR open → labels apply. Every step called once.
- Branch create returning 422 is treated as "already exists" and does
  not fail the publish.
- Contents PUT on an existing file sends the previous blob sha.
- Rejects an enforce-mode intent that omits the ``enforce`` label.
- Non-2xx responses raise :class:`GitOpsPrError` (no partial publish
  leaks into the caller's audit path).
"""

from __future__ import annotations

import base64
import json
from typing import Any
from uuid import UUID

import httpx
import pytest
from fdai.delivery.gitops_pr import (
    GitOpsPrAdapter,
    GitOpsPrConfig,
    GitOpsPrError,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.remediation_pr import RemediationPr

OWNER = "acme"
REPO = "iac"
TOKEN = "test-token"  # noqa: S105 - deterministic test literal, not a secret


def _config(**overrides: Any) -> GitOpsPrConfig:
    defaults: dict[str, Any] = {
        "owner": OWNER,
        "repo": REPO,
        "default_branch": "main",
        "api_base": "https://mock-gh.local",
    }
    defaults.update(overrides)
    return GitOpsPrConfig(**defaults)


def _pr(
    *,
    idempotency_key: str = "example-idem",
    labels: tuple[str, ...] = ("shadow", "rule:x", "action:tag-add"),
    mode: Mode = Mode.SHADOW,
) -> RemediationPr:
    return RemediationPr(
        action_id=UUID("00000000-0000-0000-0000-000000000042"),
        idempotency_key=idempotency_key,
        rule_ids=("object-storage.owner-tag.required",),
        title="[shadow] tag owner",
        body="body",
        patch='resource "azurerm_storage_account" "stg1" {}\n',
        patch_path="infra/envs/dev/stg1.tf",
        labels=labels,
        mode=mode,
    )


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler, base_url="https://mock-gh.local")


def _adapter(handler: httpx.MockTransport, **cfg: Any) -> GitOpsPrAdapter:
    return GitOpsPrAdapter(
        config=_config(**cfg),
        http_client=_client(handler),
        token=TOKEN,
    )


# ---------------------------------------------------------------------------
# Construction guards
# ---------------------------------------------------------------------------


def test_zero_timeout_is_rejected() -> None:
    with pytest.raises(ValueError, match="timeout_seconds MUST be > 0"):
        GitOpsPrAdapter(
            config=_config(timeout_seconds=0),
            http_client=httpx.AsyncClient(),
            token=TOKEN,
        )


def test_empty_token_is_rejected() -> None:
    with pytest.raises(ValueError, match="token MUST NOT be empty"):
        GitOpsPrAdapter(config=_config(), http_client=httpx.AsyncClient(), token="  ")


def test_non_https_api_base_is_rejected() -> None:
    """A plain-HTTP GitHub Enterprise override would leak the PAT and audit
    correlation id on the wire; the adapter MUST reject it at construction.
    """
    for bad in ("http://api.example.com", "ws://api.example.com", "file:///api"):
        with pytest.raises(ValueError, match="https"):
            GitOpsPrAdapter(
                config=_config(api_base=bad),
                http_client=httpx.AsyncClient(),
                token=TOKEN,
            )


# ---------------------------------------------------------------------------
# Enforce label guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enforce_mode_without_enforce_label_is_rejected() -> None:
    def _handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("adapter must not hit HTTP for a rejected intent")

    adapter = _adapter(httpx.MockTransport(_handler))
    with pytest.raises(ValueError, match="enforce"):
        await adapter.publish(_pr(mode=Mode.ENFORCE, labels=("shadow",)))


# ---------------------------------------------------------------------------
# Idempotency probe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_existing_open_pr_short_circuits_publish() -> None:
    calls: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}?{request.url.query.decode()}")
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        if request.method == "GET" and request.url.path.endswith("/pulls"):
            return httpx.Response(
                200,
                json=[
                    {
                        "number": 7,
                        "html_url": "https://github.com/acme/iac/pull/7",
                    }
                ],
            )
        raise AssertionError(f"unexpected call: {request.method} {request.url}")

    adapter = _adapter(httpx.MockTransport(_handler))
    receipt = await adapter.publish(_pr(idempotency_key="k1"))
    assert receipt.already_existed is True
    assert receipt.pr_ref == "acme/iac#7"
    assert receipt.url == "https://github.com/acme/iac/pull/7"
    # Only the probe fired.
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Full publish flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_publish_calls_every_wire_step_in_order() -> None:
    seen: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        seen.append(f"{method} {path}")

        # 1. Idempotency probe → empty
        if method == "GET" and path.endswith("/pulls"):
            return httpx.Response(200, json=[])
        # 2. base sha
        if method == "GET" and path.endswith("/git/refs/heads/main"):
            return httpx.Response(200, json={"object": {"sha": "deadbeef"}})
        # 3. Create branch
        if method == "POST" and path.endswith("/git/refs"):
            body = json.loads(request.content.decode("utf-8"))
            assert body["ref"] == "refs/heads/fdai/shadow/k1"
            assert body["sha"] == "deadbeef"
            return httpx.Response(201, json={"ref": body["ref"]})
        # 4a. Contents GET (existing file? → 404 = new file)
        if method == "GET" and "/contents/" in path:
            return httpx.Response(404, json={})
        # 4b. Contents PUT
        if method == "PUT" and "/contents/" in path:
            body = json.loads(request.content.decode("utf-8"))
            decoded = base64.b64decode(body["content"]).decode("utf-8")
            assert 'resource "azurerm_storage_account"' in decoded
            assert body["branch"] == "fdai/shadow/k1"
            return httpx.Response(201, json={"commit": {"sha": "cafe"}})
        # 5. Open draft PR
        if method == "POST" and path.endswith("/pulls"):
            body = json.loads(request.content.decode("utf-8"))
            assert body["draft"] is True
            assert body["base"] == "main"
            assert body["head"] == "fdai/shadow/k1"
            return httpx.Response(
                201,
                json={
                    "number": 42,
                    "html_url": "https://github.com/acme/iac/pull/42",
                },
            )
        # 6. Labels
        if method == "POST" and "/issues/" in path and path.endswith("/labels"):
            body = json.loads(request.content.decode("utf-8"))
            assert "shadow" in body["labels"]
            return httpx.Response(200, json=[{"name": lbl} for lbl in body["labels"]])
        raise AssertionError(f"unexpected call: {method} {path}")

    adapter = _adapter(httpx.MockTransport(_handler))
    receipt = await adapter.publish(_pr(idempotency_key="k1"))

    assert receipt.already_existed is False
    assert receipt.pr_ref == "acme/iac#42"
    assert receipt.url == "https://github.com/acme/iac/pull/42"

    # Ordering assertion - the probe MUST come first; labels MUST come last.
    assert seen[0].startswith("GET ") and seen[0].endswith("/pulls")
    assert seen[-1].endswith("/labels")


@pytest.mark.asyncio
async def test_existing_target_file_reuses_prior_blob_sha() -> None:
    """Contents PUT on an existing file MUST include the file's current blob sha."""

    def _handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        if method == "GET" and path.endswith("/pulls"):
            return httpx.Response(200, json=[])
        if method == "GET" and path.endswith("/git/refs/heads/main"):
            return httpx.Response(200, json={"object": {"sha": "deadbeef"}})
        if method == "POST" and path.endswith("/git/refs"):
            return httpx.Response(201, json={})
        if method == "GET" and "/contents/" in path:
            return httpx.Response(200, json={"sha": "old-blob"})
        if method == "PUT" and "/contents/" in path:
            body = json.loads(request.content.decode("utf-8"))
            assert body["sha"] == "old-blob"
            return httpx.Response(200, json={"commit": {"sha": "cafe"}})
        if method == "POST" and path.endswith("/pulls"):
            return httpx.Response(201, json={"number": 1, "html_url": "u"})
        if method == "POST" and "/labels" in path:
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected {method} {path}")

    adapter = _adapter(httpx.MockTransport(_handler))
    receipt = await adapter.publish(_pr(idempotency_key="k1"))
    assert receipt.already_existed is False


@pytest.mark.asyncio
async def test_branch_already_exists_is_idempotent() -> None:
    """GitHub returns 422 when the ref exists; the adapter treats that as OK."""

    def _handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        if method == "GET" and path.endswith("/pulls"):
            return httpx.Response(200, json=[])
        if method == "GET" and path.endswith("/git/refs/heads/main"):
            return httpx.Response(200, json={"object": {"sha": "deadbeef"}})
        if method == "POST" and path.endswith("/git/refs"):
            return httpx.Response(422, json={"message": "Reference already exists"})
        if method == "GET" and "/contents/" in path:
            return httpx.Response(404)
        if method == "PUT" and "/contents/" in path:
            return httpx.Response(201, json={"commit": {"sha": "cafe"}})
        if method == "POST" and path.endswith("/pulls"):
            return httpx.Response(201, json={"number": 2, "html_url": "u"})
        if method == "POST" and "/labels" in path:
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected {method} {path}")

    adapter = _adapter(httpx.MockTransport(_handler))
    receipt = await adapter.publish(_pr(idempotency_key="k1"))
    assert receipt.pr_ref == "acme/iac#2"


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_default_branch_is_fatal() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/pulls"):
            return httpx.Response(200, json=[])
        if "/git/refs/heads/" in request.url.path:
            return httpx.Response(404, json={"message": "Not Found"})
        raise AssertionError(f"unexpected {request.method} {request.url}")

    adapter = _adapter(httpx.MockTransport(_handler))
    with pytest.raises(GitOpsPrError, match="default branch"):
        await adapter.publish(_pr(idempotency_key="k1"))


@pytest.mark.asyncio
async def test_non_2xx_on_pull_creation_raises() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        if method == "GET" and path.endswith("/pulls"):
            return httpx.Response(200, json=[])
        if method == "GET" and path.endswith("/git/refs/heads/main"):
            return httpx.Response(200, json={"object": {"sha": "deadbeef"}})
        if method == "POST" and path.endswith("/git/refs"):
            return httpx.Response(201, json={})
        if method == "GET" and "/contents/" in path:
            return httpx.Response(404)
        if method == "PUT" and "/contents/" in path:
            return httpx.Response(201, json={"commit": {"sha": "cafe"}})
        if method == "POST" and path.endswith("/pulls"):
            return httpx.Response(500, text="internal error")
        raise AssertionError(f"unexpected {method} {path}")

    adapter = _adapter(httpx.MockTransport(_handler))
    with pytest.raises(GitOpsPrError, match="HTTP 500"):
        await adapter.publish(_pr(idempotency_key="k1"))


@pytest.mark.asyncio
async def test_transport_error_wraps_into_gitops_error() -> None:
    def _handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    adapter = _adapter(httpx.MockTransport(_handler))
    with pytest.raises(GitOpsPrError, match="GET"):
        await adapter.publish(_pr(idempotency_key="k1"))

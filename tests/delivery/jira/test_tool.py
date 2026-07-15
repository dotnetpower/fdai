"""httpx-mocked tests for the Jira ticketing tool executor."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from uuid import uuid4

import httpx
import pytest

from fdai.delivery.jira.tool import (
    InMemoryJiraLedger,
    JiraToolExecutor,
    JiraToolExecutorConfig,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.secret_provider import SecretNotFoundError, SecretProvider
from fdai.shared.providers.tool import (
    ToolCallOutcome,
    ToolCallReceipt,
    ToolCallRequest,
    ToolError,
    ToolExecutor,
    ToolPromotionError,
)

_ACTION_TYPE = "tool.open-incident-ticket"
_PROJECT = "OPS"


class _StaticSecrets(SecretProvider):
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values
        self.reads: list[str] = []

    async def get(self, name: str) -> str:
        self.reads.append(name)
        try:
            return self._values[name]
        except KeyError as exc:
            raise SecretNotFoundError(name) from exc


def _config(**overrides: object) -> JiraToolExecutorConfig:
    base: dict[str, object] = dict(
        base_url="https://acme.atlassian.net",
        account_email="bot@example.com",
        api_token_secret="jira/token",
        tool_map={_ACTION_TYPE: _PROJECT},
    )
    base.update(overrides)
    return JiraToolExecutorConfig(**base)  # type: ignore[arg-type]


def _request(
    *,
    mode: Mode = Mode.SHADOW,
    labels: tuple[str, ...] = ("shadow",),
    key: str = "k1",
    arguments: dict | None = None,
) -> ToolCallRequest:
    return ToolCallRequest(
        action_id=uuid4(),
        idempotency_key=key,
        action_type_name=_ACTION_TYPE,
        rule_ids=("rule-1",),
        tool_ref="ticket-queue",
        arguments=arguments if arguments is not None else {"summary": "disk full"},
        labels=labels,
        mode=mode,
    )


def _executor(
    handler,
    cfg: JiraToolExecutorConfig | None = None,
    ledger=None,
    secrets: SecretProvider | None = None,
) -> tuple[JiraToolExecutor, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ex = JiraToolExecutor(
        config=cfg or _config(),
        http_client=client,
        secrets=secrets or _StaticSecrets({"jira/token": "TKN"}),
        ledger=ledger,
    )
    return ex, client


def test_jira_executor_satisfies_protocol() -> None:
    ex, _ = _executor(lambda r: httpx.Response(200))
    assert isinstance(ex, ToolExecutor)


@pytest.mark.asyncio
async def test_shadow_is_a_real_no_op() -> None:
    called = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        called["n"] += 1
        return httpx.Response(201, json={"key": "OPS-1"})

    ledger = InMemoryJiraLedger()
    ex, client = _executor(handler, ledger=ledger)
    try:
        receipt = await ex.execute(_request(mode=Mode.SHADOW))
    finally:
        await client.aclose()

    assert receipt.outcome is ToolCallOutcome.SUCCEEDED
    assert receipt.receipt_ref.startswith("shadow:")
    assert called["n"] == 0
    assert await ledger.seen("k1") is None


@pytest.mark.asyncio
async def test_enforce_without_label_raises_promotion() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(201, json={"key": "OPS-1"})

    ex, client = _executor(handler)
    try:
        with pytest.raises(ToolPromotionError):
            await ex.execute(_request(mode=Mode.ENFORCE, labels=("shadow",)))
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_enforce_creates_issue_and_records_ledger() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"isLast": True, "issues": []})
        return httpx.Response(201, json={"id": "10001", "key": "OPS-42"})

    ledger = InMemoryJiraLedger()
    secrets = _StaticSecrets({"jira/token": "TKN"})
    ex, client = _executor(handler, ledger=ledger, secrets=secrets)
    try:
        receipt = await ex.execute(
            _request(
                mode=Mode.ENFORCE,
                labels=("shadow", "enforce"),
                arguments={
                    "summary": "disk 95% on web-a",
                    "description": "auto-opened by FDAI",
                    "labels": ["fdai", "with space"],
                },
            )
        )
    finally:
        await client.aclose()

    assert receipt.outcome is ToolCallOutcome.SUCCEEDED
    assert receipt.receipt_ref == "OPS-42"
    assert await ledger.seen("k1") == "OPS-42"

    assert captured[0].method == "GET"
    assert captured[0].url.path.endswith("/rest/api/3/search/jql")
    digest = hashlib.sha256(b"k1").hexdigest()[:32]
    assert f"fdai-idem-{digest}" in captured[0].url.params["jql"]
    req = captured[1]
    assert str(req.url).endswith("/rest/api/3/issue")
    expected_basic = base64.b64encode(b"bot@example.com:TKN").decode("ascii")
    assert req.headers["Authorization"] == f"Basic {expected_basic}"
    body = json.loads(req.content)
    assert body["fields"]["project"]["key"] == "OPS"
    assert body["fields"]["summary"] == "disk 95% on web-a"
    assert body["fields"]["issuetype"]["name"] == "Task"
    # labels with spaces are dropped; valid ones kept
    assert body["fields"]["labels"][0] == "fdai"
    assert body["fields"]["labels"] == ["fdai", f"fdai-idem-{digest}"]
    # description wrapped in Atlassian Document Format
    assert body["fields"]["description"]["type"] == "doc"
    assert secrets.reads == ["jira/token"]


@pytest.mark.asyncio
async def test_caller_cannot_inject_another_idempotency_label() -> None:
    captured: list[httpx.Request] = []
    other_digest = hashlib.sha256(b"other-key").hexdigest()[:32]

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"isLast": True, "issues": []})
        return httpx.Response(201, json={"key": "OPS-42"})

    ex, client = _executor(handler)
    try:
        await ex.execute(
            _request(
                mode=Mode.ENFORCE,
                labels=("shadow", "enforce"),
                arguments={
                    "summary": "disk full",
                    "labels": [f"fdai-idem-{other_digest}", "operator-label"],
                },
            )
        )
    finally:
        await client.aclose()

    body = json.loads(captured[1].content)
    own_digest = hashlib.sha256(b"k1").hexdigest()[:32]
    assert body["fields"]["labels"] == ["operator-label", f"fdai-idem-{own_digest}"]


@pytest.mark.asyncio
async def test_idempotency_short_circuits_no_duplicate() -> None:
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if request.method == "GET":
            return httpx.Response(200, json={"isLast": True, "issues": []})
        return httpx.Response(201, json={"key": "OPS-7"})

    ledger = InMemoryJiraLedger()
    ex, client = _executor(handler, ledger=ledger)
    try:
        first = await ex.execute(_request(mode=Mode.ENFORCE, labels=("shadow", "enforce")))
        second = await ex.execute(_request(mode=Mode.ENFORCE, labels=("shadow", "enforce")))
    finally:
        await client.aclose()

    assert first.outcome is ToolCallOutcome.SUCCEEDED
    assert second.outcome is ToolCallOutcome.ALREADY_APPLIED
    assert second.already_existed is True
    assert calls["n"] == 2  # one reconciliation search + one real create


@pytest.mark.asyncio
async def test_wrong_project_ledger_hit_fails_closed() -> None:
    ledger = InMemoryJiraLedger()
    await ledger.record("k1", "OTHER-7")
    ex, client = _executor(lambda request: httpx.Response(500), ledger=ledger)
    try:
        with pytest.raises(ToolError) as exc:
            await ex.execute(_request(mode=Mode.ENFORCE, labels=("shadow", "enforce")))
    finally:
        await client.aclose()
    assert exc.value.kind == "protocol"


@pytest.mark.asyncio
async def test_unmapped_action_fails_even_when_ledger_has_prior_receipt() -> None:
    ledger = InMemoryJiraLedger()
    await ledger.record("k1", "OPS-7")
    ex, client = _executor(
        lambda request: httpx.Response(500),
        cfg=_config(tool_map={}),
        ledger=ledger,
    )
    try:
        with pytest.raises(ToolError) as exc:
            await ex.execute(_request(mode=Mode.SHADOW))
    finally:
        await client.aclose()
    assert exc.value.kind == "config"


@pytest.mark.asyncio
async def test_unmapped_action_type_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(201, json={"key": "OPS-1"})

    ex, client = _executor(handler, cfg=_config(tool_map={}))
    try:
        with pytest.raises(ToolError) as exc:
            await ex.execute(_request(mode=Mode.SHADOW))
    finally:
        await client.aclose()
    assert exc.value.kind == "config"


@pytest.mark.asyncio
async def test_http_error_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    ex, client = _executor(handler)
    try:
        with pytest.raises(ToolError) as exc:
            await ex.execute(_request(mode=Mode.ENFORCE, labels=("shadow", "enforce")))
    finally:
        await client.aclose()
    assert exc.value.kind == "http"


@pytest.mark.asyncio
async def test_create_4xx_releases_claim_for_safe_retry() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if request.method == "GET":
            return httpx.Response(200, json={"isLast": True, "issues": []})
        attempts += 1
        return httpx.Response(400, json={"errorMessages": ["invalid issue"]})

    ledger = InMemoryJiraLedger()
    ex, client = _executor(handler, ledger=ledger)
    request = _request(mode=Mode.ENFORCE, labels=("shadow", "enforce"))
    try:
        for _ in range(2):
            with pytest.raises(ToolError) as exc:
                await ex.execute(request)
            assert exc.value.kind == "http"
    finally:
        await client.aclose()

    assert attempts == 2


@pytest.mark.asyncio
async def test_create_5xx_keeps_claim_quarantined() -> None:
    posts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        if request.method == "GET":
            return httpx.Response(200, json={"isLast": True, "issues": []})
        posts += 1
        return httpx.Response(503, json={"errorMessages": ["unavailable"]})

    ledger = InMemoryJiraLedger()
    ex, client = _executor(handler, ledger=ledger)
    request = _request(mode=Mode.ENFORCE, labels=("shadow", "enforce"))
    try:
        with pytest.raises(ToolError) as first:
            await ex.execute(request)
        with pytest.raises(ToolError) as second:
            await ex.execute(request)
    finally:
        await client.aclose()

    assert first.value.kind == "http"
    assert second.value.kind == "conflict"
    assert posts == 1


@pytest.mark.asyncio
async def test_missing_key_in_response_maps_to_failed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"isLast": True, "issues": []})
        return httpx.Response(201, json={"id": "10001"})  # no key

    ledger = InMemoryJiraLedger()
    ex, client = _executor(handler, ledger=ledger)
    try:
        receipt = await ex.execute(_request(mode=Mode.ENFORCE, labels=("shadow", "enforce")))
    finally:
        await client.aclose()

    assert receipt.outcome is ToolCallOutcome.FAILED
    assert await ledger.seen("k1") is None  # failure never records the ledger


@pytest.mark.asyncio
async def test_create_response_from_wrong_project_maps_to_failed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"isLast": True, "issues": []})
        return httpx.Response(201, json={"key": "OTHER-1"})

    ex, client = _executor(handler)
    try:
        receipt = await ex.execute(
            _request(mode=Mode.ENFORCE, labels=("shadow", "enforce"))
        )
    finally:
        await client.aclose()

    assert receipt.outcome is ToolCallOutcome.FAILED


@pytest.mark.asyncio
async def test_reconciliation_recovers_issue_after_create_record_crash() -> None:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"isLast": True, "issues": [{"key": "OPS-77"}]},
            )
        raise AssertionError("reconciled issue MUST NOT be created again")

    ledger = InMemoryJiraLedger()
    ex, client = _executor(handler, ledger=ledger)
    try:
        receipt = await ex.execute(
            _request(mode=Mode.ENFORCE, labels=("shadow", "enforce"))
        )
    finally:
        await client.aclose()

    assert receipt.outcome is ToolCallOutcome.ALREADY_APPLIED
    assert receipt.receipt_ref == "OPS-77"
    assert await ledger.seen("k1") == "OPS-77"
    assert calls == ["GET"]


@pytest.mark.asyncio
async def test_non_json_response_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, text="<html>oops</html>")

    ex, client = _executor(handler)
    try:
        with pytest.raises(ToolError) as exc:
            await ex.execute(_request(mode=Mode.ENFORCE, labels=("shadow", "enforce")))
    finally:
        await client.aclose()
    assert exc.value.kind == "protocol"


@pytest.mark.asyncio
async def test_response_over_byte_cap_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"key": "OPS-1", "pad": "z" * 500})

    ex, client = _executor(handler, cfg=_config(max_response_bytes=64))
    try:
        with pytest.raises(ToolError) as exc:
            await ex.execute(_request(mode=Mode.ENFORCE, labels=("shadow", "enforce")))
    finally:
        await client.aclose()
    assert exc.value.kind == "protocol"


@pytest.mark.asyncio
async def test_create_response_over_byte_cap_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"isLast": True, "issues": []})
        return httpx.Response(201, json={"key": "OPS-1", "pad": "z" * 500})

    ex, client = _executor(handler, cfg=_config(max_response_bytes=64))
    try:
        with pytest.raises(ToolError) as exc:
            await ex.execute(_request(mode=Mode.ENFORCE, labels=("shadow", "enforce")))
    finally:
        await client.aclose()
    assert exc.value.kind == "protocol"


@pytest.mark.asyncio
async def test_malformed_search_issue_never_becomes_create_miss() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(200, json={"isLast": True, "issues": [{"id": "10001"}]})

    ex, client = _executor(handler)
    try:
        with pytest.raises(ToolError) as exc:
            await ex.execute(_request(mode=Mode.ENFORCE, labels=("shadow", "enforce")))
    finally:
        await client.aclose()
    assert exc.value.kind == "protocol"


@pytest.mark.asyncio
async def test_concurrent_calls_allow_only_claimant_to_post() -> None:
    searches_arrived = 0
    both_searching = asyncio.Event()
    posts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal searches_arrived, posts
        if request.method == "GET":
            searches_arrived += 1
            if searches_arrived == 2:
                both_searching.set()
            await both_searching.wait()
            return httpx.Response(200, json={"isLast": True, "issues": []})
        posts += 1
        return httpx.Response(201, json={"key": "OPS-88"})

    ledger = InMemoryJiraLedger()
    first, first_client = _executor(handler, ledger=ledger)
    second, second_client = _executor(handler, ledger=ledger)
    request = _request(mode=Mode.ENFORCE, labels=("shadow", "enforce"))
    try:
        results = await asyncio.gather(
            first.execute(request),
            second.execute(request),
            return_exceptions=True,
        )
    finally:
        await first_client.aclose()
        await second_client.aclose()

    assert posts == 1
    assert sum(isinstance(result, ToolCallReceipt) for result in results) == 1
    conflicts = [result for result in results if isinstance(result, ToolError)]
    assert len(conflicts) == 1
    assert conflicts[0].kind == "conflict"


@pytest.mark.asyncio
async def test_concurrent_reconciliation_completion_wins_before_post() -> None:
    completed = asyncio.Event()
    searches = 0
    posts = 0

    class SignalingLedger(InMemoryJiraLedger):
        async def record(self, key: str, receipt_ref: str) -> None:
            await super().record(key, receipt_ref)
            completed.set()

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal searches, posts
        if request.method == "GET":
            searches += 1
            if searches == 1:
                await completed.wait()
                return httpx.Response(200, json={"isLast": True, "issues": []})
            return httpx.Response(
                200,
                json={"isLast": True, "issues": [{"key": "OPS-91"}]},
            )
        posts += 1
        return httpx.Response(201, json={"key": "OPS-92"})

    ledger = SignalingLedger()
    claimant, claimant_client = _executor(handler, ledger=ledger)
    reconciler, reconciler_client = _executor(handler, ledger=ledger)
    request = _request(mode=Mode.ENFORCE, labels=("shadow", "enforce"))
    try:
        results = await asyncio.gather(
            claimant.execute(request),
            reconciler.execute(request),
        )
    finally:
        await claimant_client.aclose()
        await reconciler_client.aclose()

    assert posts == 0
    assert {result.receipt_ref for result in results} == {"OPS-91"}
    assert all(result.outcome is ToolCallOutcome.ALREADY_APPLIED for result in results)


@pytest.mark.asyncio
async def test_pre_post_ledger_failure_releases_claim() -> None:
    class FailingSeenLedger(InMemoryJiraLedger):
        def __init__(self) -> None:
            super().__init__()
            self.seen_calls = 0

        async def seen(self, key: str) -> str | None:
            self.seen_calls += 1
            if self.seen_calls == 2:
                raise RuntimeError("injected pre-POST ledger failure")
            return await super().seen(key)

    posts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        if request.method == "GET":
            return httpx.Response(200, json={"isLast": True, "issues": []})
        posts += 1
        return httpx.Response(201, json={"key": "OPS-93"})

    ledger = FailingSeenLedger()
    ex, client = _executor(handler, ledger=ledger)
    request = _request(mode=Mode.ENFORCE, labels=("shadow", "enforce"))
    try:
        with pytest.raises(RuntimeError, match="pre-POST ledger failure"):
            await ex.execute(request)
        retried = await ex.execute(request)
    finally:
        await client.aclose()

    assert retried.outcome is ToolCallOutcome.SUCCEEDED
    assert posts == 1


@pytest.mark.asyncio
async def test_cancellation_during_search_releases_pre_post_claim() -> None:
    search_started = asyncio.Event()
    unblock_search = asyncio.Event()
    posts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        if request.method == "GET":
            search_started.set()
            await unblock_search.wait()
            return httpx.Response(200, json={"isLast": True, "issues": []})
        posts += 1
        return httpx.Response(201, json={"key": "OPS-94"})

    ledger = InMemoryJiraLedger()
    ex, client = _executor(handler, ledger=ledger)
    request = _request(mode=Mode.ENFORCE, labels=("shadow", "enforce"))
    cancelled = asyncio.create_task(ex.execute(request))
    await search_started.wait()
    cancelled.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        unblock_search.set()
        retried = await ex.execute(request)
    finally:
        await client.aclose()

    assert retried.outcome is ToolCallOutcome.SUCCEEDED
    assert posts == 1


@pytest.mark.asyncio
async def test_missing_secret_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(201, json={"key": "OPS-1"})

    ex, client = _executor(handler, secrets=_StaticSecrets({}))
    try:
        with pytest.raises(SecretNotFoundError):
            await ex.execute(_request(mode=Mode.ENFORCE, labels=("shadow", "enforce")))
    finally:
        await client.aclose()


def test_config_rejects_plaintext_url() -> None:
    with pytest.raises(ValueError, match="https://"):
        _config(base_url="http://acme.atlassian.net")


def test_config_rejects_empty_token_secret() -> None:
    with pytest.raises(ValueError, match="api_token_secret"):
        _config(api_token_secret="")


def test_config_rejects_project_key_that_could_break_jql() -> None:
    with pytest.raises(ValueError, match="project keys MUST match"):
        _config(tool_map={_ACTION_TYPE: 'OPS" OR project IS NOT EMPTY'})

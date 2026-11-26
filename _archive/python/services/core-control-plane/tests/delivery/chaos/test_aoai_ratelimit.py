"""Unit tests for the Azure OpenAI rate-limit injector + probe.

The request function is faked (and ``urllib`` is monkeypatched for the
factory test), so these never touch a real endpoint - they lock the
load/stop lifecycle, the 429 detection, and the status-code mapping.
"""

from __future__ import annotations

import threading
import urllib.error

import fdai.delivery.chaos.aoai_ratelimit as ar
import pytest


def test_injector_fault_type() -> None:
    inj = ar.AoaiRateLimitInjector(request_fn=lambda: 200)
    assert inj.fault_type == "rate_limit"


def test_injector_rejects_non_positive_concurrency() -> None:
    with pytest.raises(ValueError, match="concurrency"):
        ar.AoaiRateLimitInjector(request_fn=lambda: 200, concurrency=0)


async def test_inject_fires_requests_and_stop_joins() -> None:
    fired = threading.Event()
    count = {"n": 0}
    lock = threading.Lock()

    def rf() -> int:
        with lock:
            count["n"] += 1
        fired.set()
        return 429

    inj = ar.AoaiRateLimitInjector(request_fn=rf, concurrency=3)
    await inj.inject(target="model-deployment:chat", params={})
    assert fired.wait(timeout=5.0), "no request was fired"
    await inj.stop(target="model-deployment:chat")
    assert inj._threads == []  # all workers joined
    assert count["n"] > 0


async def test_param_override_sets_concurrency() -> None:
    inj = ar.AoaiRateLimitInjector(request_fn=lambda: 429, concurrency=1)
    await inj.inject(target="model-deployment:chat", params={"concurrency": "4"})
    started = len(inj._threads)
    await inj.stop(target="model-deployment:chat")
    assert started == 4


async def test_stop_without_inject_is_safe() -> None:
    inj = ar.AoaiRateLimitInjector(request_fn=lambda: 200)
    await inj.stop(target="model-deployment:chat")
    assert inj._threads == []


def test_probe_rejects_non_positive_samples() -> None:
    with pytest.raises(ValueError, match="samples"):
        ar.AoaiRateLimitProbe(request_fn=lambda: 429, samples=0)


async def test_probe_true_when_any_429() -> None:
    seq = iter([200, 200, 429, 200])
    probe = ar.AoaiRateLimitProbe(request_fn=lambda: next(seq), samples=4)
    assert await probe.observed(signal="rate_limit", targets=["model-deployment:chat"]) is True


async def test_probe_false_when_all_ok() -> None:
    probe = ar.AoaiRateLimitProbe(request_fn=lambda: 200, samples=4)
    assert await probe.observed(signal="rate_limit", targets=["model-deployment:chat"]) is False


# --------------------------------------------------------------------------
# stdlib urllib factory status-code mapping
# --------------------------------------------------------------------------


class _Resp:
    status = 200

    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *a: object) -> None:
        return None


def _factory():  # type: ignore[no-untyped-def]
    return ar.build_aoai_request_fn(
        endpoint="https://x.openai.azure.com/",
        deployment="chat",
        token_provider=lambda: "tok",
        prompt="hi",
    )


def test_factory_returns_status_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ar.urllib.request, "urlopen", lambda *a, **k: _Resp())
    assert _factory()() == 200


def test_factory_maps_httperror_to_code(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: object, **k: object) -> object:
        raise urllib.error.HTTPError("u", 429, "too many", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(ar.urllib.request, "urlopen", boom)
    assert _factory()() == 429


def test_factory_maps_transport_error_to_sentinel(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: object, **k: object) -> object:
        raise OSError("connection reset")

    monkeypatch.setattr(ar.urllib.request, "urlopen", boom)
    assert _factory()() == -1

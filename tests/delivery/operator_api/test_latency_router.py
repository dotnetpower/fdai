"""Tests for :class:`LatencyRoutedChatBackend` warm-up + p50 selection."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from fdai.delivery.operator_api.routes.chat import LatencyRoutedChatBackend, describe_backend
from fdai.delivery.operator_api.routes.chat_backend_common import (
    ChatBackendUnavailableError,
    ChatContentPolicyError,
)


class _FixedLatencyBackend:
    """Async backend that sleeps a fixed amount so the router measures it."""

    def __init__(self, *, model: str, delay_ms: int) -> None:
        self._model = model
        self._delay_ms = delay_ms
        self.calls = 0

    async def answer(
        self,
        *,
        prompt: str,  # noqa: ARG002
        view_context: dict[str, Any],  # noqa: ARG002
        history: list[dict[str, str]],  # noqa: ARG002
    ) -> dict[str, Any]:
        self.calls += 1
        await asyncio.sleep(self._delay_ms / 1000)
        return {"answer": "ok", "model": self._model}


class _StructuredBackend(_FixedLatencyBackend):
    def __init__(self, *, result: object) -> None:
        super().__init__(model="structured", delay_ms=0)
        self._result = result

    async def complete_structured(self, **_kwargs: object) -> object:
        self.calls += 1
        return self._result


class _RaisingBackend:
    def __init__(self, *, model: str) -> None:
        self._model = model
        self.calls = 0

    async def answer(
        self,
        *,
        prompt: str,  # noqa: ARG002
        view_context: dict[str, Any],  # noqa: ARG002
        history: list[dict[str, str]],  # noqa: ARG002
    ) -> dict[str, Any]:
        self.calls += 1
        raise RuntimeError("upstream down")


class _PolicyBlockedBackend(_RaisingBackend):
    async def answer(self, **_kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        raise ChatContentPolicyError(stage="input")

    async def answer_stream(self, **_kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        self.calls += 1
        raise ChatContentPolicyError(stage="input")
        yield {}


class _EmptyBackend:
    def __init__(self) -> None:
        self.calls = 0

    async def answer(
        self,
        *,
        prompt: str,  # noqa: ARG002
        view_context: dict[str, Any],  # noqa: ARG002
        history: list[dict[str, str]],  # noqa: ARG002
    ) -> dict[str, Any]:
        self.calls += 1
        return {"answer": "   ", "model": "empty"}


class _NeverBackend:
    def __init__(self) -> None:
        self.calls = 0

    async def answer(
        self,
        *,
        prompt: str,  # noqa: ARG002
        view_context: dict[str, Any],  # noqa: ARG002
        history: list[dict[str, str]],  # noqa: ARG002
    ) -> dict[str, Any]:
        self.calls += 1
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def answer_stream(
        self,
        *,
        prompt: str,  # noqa: ARG002
        view_context: dict[str, Any],  # noqa: ARG002
        history: list[dict[str, str]],  # noqa: ARG002
    ) -> AsyncIterator[dict[str, Any]]:
        self.calls += 1
        await asyncio.Event().wait()
        yield {"type": "done", "answer": "unreachable"}


class _StreamingBackend:
    def __init__(self, *, fail_before: bool = False, fail_after: bool = False) -> None:
        self._fail_before = fail_before
        self._fail_after = fail_after
        self.calls = 0

    async def answer(
        self,
        *,
        prompt: str,  # noqa: ARG002
        view_context: dict[str, Any],  # noqa: ARG002
        history: list[dict[str, str]],  # noqa: ARG002
    ) -> dict[str, Any]:
        return {"answer": "stream fallback", "model": "stream"}

    async def answer_stream(
        self,
        *,
        prompt: str,  # noqa: ARG002
        view_context: dict[str, Any],  # noqa: ARG002
        history: list[dict[str, str]],  # noqa: ARG002
    ) -> AsyncIterator[dict[str, Any]]:
        self.calls += 1
        if self._fail_before:
            raise RuntimeError("failed before token")
        yield {"type": "token", "delta": "hello"}
        if self._fail_after:
            raise RuntimeError("failed after token")
        yield {"type": "done", "answer": "hello", "model": "stream"}


class _EmptyStreamingBackend(_EmptyBackend):
    async def answer_stream(
        self,
        *,
        prompt: str,  # noqa: ARG002
        view_context: dict[str, Any],  # noqa: ARG002
        history: list[dict[str, str]],  # noqa: ARG002
    ) -> AsyncIterator[dict[str, Any]]:
        self.calls += 1
        yield {"type": "done", "answer": "", "model": "empty"}


class TestRouterConstruction:
    def test_requires_one_or_more_candidates(self) -> None:
        with pytest.raises(ValueError, match=">= 1"):
            LatencyRoutedChatBackend(candidates=[])

    def test_rejects_duplicate_names(self) -> None:
        a = _FixedLatencyBackend(model="dup", delay_ms=1)
        b = _FixedLatencyBackend(model="dup", delay_ms=1)
        with pytest.raises(ValueError, match="unique"):
            LatencyRoutedChatBackend(candidates=[("dup", a), ("dup", b)])

    def test_rejects_non_positive_turn_deadline(self) -> None:
        a = _FixedLatencyBackend(model="a", delay_ms=1)
        b = _FixedLatencyBackend(model="b", delay_ms=1)
        with pytest.raises(ValueError, match="turn_timeout_seconds"):
            LatencyRoutedChatBackend(
                candidates=[("a", a), ("b", b)],
                turn_timeout_seconds=0,
            )

    def test_rejects_direct_vision_routing_cycle(self) -> None:
        router = LatencyRoutedChatBackend(
            candidates=[("text", _FixedLatencyBackend(model="text", delay_ms=1))]
        )

        with pytest.raises(ValueError, match="routing cycle"):
            router.bind_vision_backend(router)

    def test_rejects_indirect_vision_routing_cycle(self) -> None:
        first = LatencyRoutedChatBackend(
            candidates=[("first", _FixedLatencyBackend(model="first", delay_ms=1))]
        )
        second = LatencyRoutedChatBackend(
            candidates=[("second", _FixedLatencyBackend(model="second", delay_ms=1))]
        )
        first.bind_vision_backend(second)

        with pytest.raises(ValueError, match="routing cycle"):
            second.bind_vision_backend(first)

    def test_cold_candidate_stats_are_json_safe(self) -> None:
        a = _FixedLatencyBackend(model="a", delay_ms=1)
        b = _FixedLatencyBackend(model="b", delay_ms=1)
        router = LatencyRoutedChatBackend(candidates=[("a", a), ("b", b)])

        descriptor = describe_backend(router)

        assert descriptor["router"]["candidates"] == [
            {
                "deployment": "a",
                "p50_ms": None,
                "p95_ms": None,
                "samples": 0,
                "history_ms": [],
                "ttft_p50_ms": None,
                "ttft_p95_ms": None,
                "ttft_samples": 0,
                "ttft_history_ms": [],
            },
            {
                "deployment": "b",
                "p50_ms": None,
                "p95_ms": None,
                "samples": 0,
                "history_ms": [],
                "ttft_p50_ms": None,
                "ttft_p95_ms": None,
                "ttft_samples": 0,
                "ttft_history_ms": [],
            },
        ]


class TestRouterWarmupAndSelection:
    async def _make_router(
        self,
    ) -> tuple[
        LatencyRoutedChatBackend, _FixedLatencyBackend, _FixedLatencyBackend, _FixedLatencyBackend
    ]:
        fast = _FixedLatencyBackend(model="fast", delay_ms=5)
        mid = _FixedLatencyBackend(model="mid", delay_ms=25)
        slow = _FixedLatencyBackend(model="slow", delay_ms=60)
        router = LatencyRoutedChatBackend(
            candidates=[("fast", fast), ("mid", mid), ("slow", slow)],
        )
        return router, fast, mid, slow

    async def test_routes_image_turns_to_an_independent_vision_pool(self) -> None:
        text_a = _FixedLatencyBackend(model="text-a", delay_ms=1)
        text_b = _FixedLatencyBackend(model="text-b", delay_ms=1)
        vision_a = _FixedLatencyBackend(model="vision-a", delay_ms=1)
        vision_b = _FixedLatencyBackend(model="vision-b", delay_ms=1)
        router = LatencyRoutedChatBackend(
            candidates=[("text-a", text_a), ("text-b", text_b)],
        )
        vision = LatencyRoutedChatBackend(
            candidates=[("vision-a", vision_a), ("vision-b", vision_b)],
            vision_capable=True,
        )
        router.bind_vision_backend(vision)

        text_reply = await router.answer(prompt="text", view_context={}, history=[])
        image_reply = await router.answer(
            prompt="image",
            view_context={"_attachments": [{"data_url": "data:image/png;base64,AA=="}]},
            history=[],
        )

        assert text_reply["model"] == "text-a"
        assert image_reply["model"] == "vision-a"
        assert text_a.calls == 1
        assert vision_a.calls == 1

    async def test_image_turn_fails_closed_without_a_vision_pool(self) -> None:
        router = LatencyRoutedChatBackend(
            candidates=[
                ("text-a", _FixedLatencyBackend(model="text-a", delay_ms=1)),
                ("text-b", _FixedLatencyBackend(model="text-b", delay_ms=1)),
            ],
        )

        with pytest.raises(ChatBackendUnavailableError, match="vision model pool unavailable"):
            await router.answer(
                prompt="image",
                view_context={"_attachments": [{"data_url": "data:image/png;base64,AA=="}]},
                history=[],
            )

    async def test_structured_image_turn_validates_vision_pool_output(self) -> None:
        router = LatencyRoutedChatBackend(
            candidates=[("text", _FixedLatencyBackend(model="text", delay_ms=1))]
        )
        vision = _StructuredBackend(result={"intent": "inspect_image"})
        router.bind_vision_backend(vision)

        result = await router.complete_structured(
            system_prompt="system",
            user_content=[{"type": "image_url"}],
            schema_name="intent",
            schema={"type": "object"},
            max_tokens=64,
        )

        assert result == {"intent": "inspect_image"}
        assert vision.calls == 1

    async def test_structured_image_turn_rejects_non_mapping_output(self) -> None:
        router = LatencyRoutedChatBackend(
            candidates=[("text", _FixedLatencyBackend(model="text", delay_ms=1))]
        )
        router.bind_vision_backend(_StructuredBackend(result=["invalid"]))

        with pytest.raises(
            ChatBackendUnavailableError,
            match="vision model pool returned invalid structured output",
        ):
            await router.complete_structured(
                system_prompt="system",
                user_content=[{"type": "image_url"}],
                schema_name="intent",
                schema={"type": "object"},
                max_tokens=64,
            )

    async def test_benchmark_samples_text_and_vision_pools(self) -> None:
        text = [
            _FixedLatencyBackend(model="text-a", delay_ms=1),
            _FixedLatencyBackend(model="text-b", delay_ms=1),
        ]
        vision_candidates = [
            _FixedLatencyBackend(model="vision-a", delay_ms=1),
            _FixedLatencyBackend(model="vision-b", delay_ms=1),
        ]
        router = LatencyRoutedChatBackend(
            candidates=[("text-a", text[0]), ("text-b", text[1])],
        )
        router.bind_vision_backend(
            LatencyRoutedChatBackend(
                candidates=[("vision-a", vision_candidates[0]), ("vision-b", vision_candidates[1])],
                vision_capable=True,
            )
        )

        await router.benchmark(rounds=1)

        assert [candidate.calls for candidate in text] == [1, 1]
        assert [candidate.calls for candidate in vision_candidates] == [1, 1]

    async def test_stream_routes_image_turns_to_the_vision_pool(self) -> None:
        text = [_StreamingBackend(), _StreamingBackend()]
        vision_candidates = [_StreamingBackend(), _StreamingBackend()]
        router = LatencyRoutedChatBackend(
            candidates=[("text-a", text[0]), ("text-b", text[1])],
        )
        router.bind_vision_backend(
            LatencyRoutedChatBackend(
                candidates=[("vision-a", vision_candidates[0]), ("vision-b", vision_candidates[1])],
                vision_capable=True,
            )
        )

        events = [
            event
            async for event in router.answer_stream(
                prompt="image",
                view_context={"_attachments": [{"data_url": "data:image/png;base64,AA=="}]},
                history=[],
            )
        ]

        assert events[-1]["model"] == "vision-a"
        assert [candidate.calls for candidate in text] == [0, 0]
        assert [candidate.calls for candidate in vision_candidates] == [1, 0]

    async def test_warmup_rotates_every_candidate_before_pinning(self) -> None:
        router, fast, mid, slow = await self._make_router()
        # Fire 6 turns - warmup requires 2 samples per candidate (3*2=6).
        picks: list[str] = []
        for _ in range(6):
            reply = await router.answer(prompt="hi", view_context={}, history=[])
            picks.append(reply["router"]["chose"])
        # Every candidate got exactly two calls during warm-up.
        assert fast.calls == 2
        assert mid.calls == 2
        assert slow.calls == 2
        # And warm-up reason is stamped on every one of those turns.
        assert all(picks.count(name) == 2 for name in ("fast", "mid", "slow"))

    async def test_steady_state_prefers_lowest_p50(self) -> None:
        router, fast, mid, slow = await self._make_router()
        # Warm-up first.
        for _ in range(6):
            await router.answer(prompt="hi", view_context={}, history=[])
        # After warm-up the fast backend has the lowest p50; the next 3
        # turns should all pick it.
        for _ in range(3):
            reply = await router.answer(prompt="hi", view_context={}, history=[])
            assert reply["router"]["chose"] == "fast"
            assert reply["router"]["reason"] == "lowest-p50"
            assert reply["model"] == "fast"
        assert fast.calls == 5  # 2 warmup + 3 steady
        assert mid.calls == 2
        assert slow.calls == 2

    async def test_response_carries_full_candidate_stats(self) -> None:
        router, *_ = await self._make_router()
        for _ in range(6):
            await router.answer(prompt="hi", view_context={}, history=[])
        reply = await router.answer(prompt="hi", view_context={}, history=[])
        stats = {c["deployment"]: c for c in reply["router"]["candidates"]}
        assert set(stats.keys()) == {"fast", "mid", "slow"}
        assert stats["fast"]["samples"] >= 2
        assert stats["fast"]["p50_ms"] < stats["slow"]["p50_ms"]

    async def test_stats_expose_p95_and_history_for_sparkline(self) -> None:
        router, *_ = await self._make_router()
        # Run enough turns to fill the rolling window at least partially.
        for _ in range(9):
            await router.answer(prompt="hi", view_context={}, history=[])
        stats = {c["deployment"]: c for c in router.stats()}
        for name in ("fast", "mid", "slow"):
            entry = stats[name]
            assert entry["samples"] == len(entry["history_ms"])
            assert entry["samples"] > 0
            # p95 >= p50 by definition (nearest-rank).
            assert entry["p95_ms"] >= entry["p50_ms"]
            # history_ms carries integers in the router's window bounds.
            for sample in entry["history_ms"]:
                assert isinstance(sample, int)
                assert sample >= 0

    async def test_user_preference_pins_an_allowlisted_candidate(self) -> None:
        router, fast, _, slow = await self._make_router()

        reply = await router.answer(
            prompt="hi",
            view_context={},
            history=[],
            preferred_model="slow",
        )

        assert reply["model"] == "slow"
        assert reply["router"]["reason"] == "user-preferred"
        assert slow.calls == 1
        assert fast.calls == 0

    async def test_unknown_preference_falls_back_to_auto(self) -> None:
        router, fast, _, _ = await self._make_router()

        reply = await router.answer(
            prompt="hi",
            view_context={},
            history=[],
            preferred_model="not-deployed",
        )

        assert reply["model"] == "fast"
        assert reply["router"]["reason"] == "warmup"
        assert fast.calls == 1

    async def test_stream_records_true_first_token_latency(self) -> None:
        first = _StreamingBackend()
        second = _StreamingBackend()
        router = LatencyRoutedChatBackend(candidates=[("first", first), ("second", second)])

        events = [
            event
            async for event in router.answer_stream(
                prompt="hi",
                view_context={},
                history=[],
                preferred_model="second",
            )
        ]

        stats = {entry["deployment"]: entry for entry in router.stats()}
        assert events[-1]["model"] == "second"
        assert events[-1]["router"]["reason"] == "user-preferred"
        assert stats["second"]["ttft_samples"] == 1
        assert stats["second"]["ttft_p50_ms"] is not None


class TestRouterFailureHandling:
    async def test_content_policy_block_does_not_fail_over_or_penalize(self) -> None:
        blocked = _PolicyBlockedBackend(model="blocked")
        good = _FixedLatencyBackend(model="good", delay_ms=1)
        router = LatencyRoutedChatBackend(candidates=[("blocked", blocked), ("good", good)])

        with pytest.raises(ChatContentPolicyError):
            await router.answer(prompt="hi", view_context={}, history=[])

        assert blocked.calls == 1
        assert good.calls == 0
        assert router.stats()[0]["samples"] == 0

    async def test_stream_content_policy_block_does_not_fail_over_or_penalize(self) -> None:
        blocked = _PolicyBlockedBackend(model="blocked")
        good = _StreamingBackend()
        router = LatencyRoutedChatBackend(candidates=[("blocked", blocked), ("good", good)])

        with pytest.raises(ChatContentPolicyError):
            await _collect_stream(router)

        assert blocked.calls == 1
        assert good.calls == 0
        assert router.stats()[0]["samples"] == 0

    async def test_total_turn_deadline_bounds_all_candidate_attempts(self) -> None:
        first = _NeverBackend()
        second = _NeverBackend()
        router = LatencyRoutedChatBackend(
            candidates=[("first", first), ("second", second)],
            turn_timeout_seconds=0.05,
        )

        with pytest.raises(TimeoutError, match="deadline"):
            await asyncio.wait_for(
                router.answer(prompt="hi", view_context={}, history=[]),
                timeout=0.2,
            )

        assert first.calls == 1
        assert second.calls == 1

    async def test_stream_deadline_fails_over_only_before_first_token(self) -> None:
        first = _NeverBackend()
        second = _NeverBackend()
        router = LatencyRoutedChatBackend(
            candidates=[("first", first), ("second", second)],
            turn_timeout_seconds=0.05,
        )

        with pytest.raises(TimeoutError, match="deadline"):
            await asyncio.wait_for(
                _collect_stream(router),
                timeout=0.2,
            )

        assert first.calls == 1
        assert second.calls == 1

    async def test_failure_penalizes_candidate_and_fails_over(self) -> None:
        good = _FixedLatencyBackend(model="good", delay_ms=5)
        bad = _RaisingBackend(model="bad")
        router = LatencyRoutedChatBackend(
            candidates=[("bad", bad), ("good", good)],  # ordered so ties go to "bad" first
        )
        reply = await router.answer(prompt="hi", view_context={}, history=[])

        assert bad.calls == 1
        assert good.calls == 1
        assert reply["model"] == "good"
        assert reply["router"]["reason"] == "failover"
        stats = {c["deployment"]: c for c in router.stats()}
        assert stats["bad"]["samples"] == 1
        assert stats["bad"]["p50_ms"] is not None
        assert stats["bad"]["p95_ms"] is not None
        assert stats["bad"]["p50_ms"] >= 20_000  # penalty is 30_000ms

    async def test_all_candidate_failures_reraise_last_error(self) -> None:
        first = _RaisingBackend(model="first")
        second = _RaisingBackend(model="second")
        router = LatencyRoutedChatBackend(candidates=[("first", first), ("second", second)])

        with pytest.raises(RuntimeError, match="upstream down"):
            await router.answer(prompt="hi", view_context={}, history=[])

        assert first.calls == 1
        assert second.calls == 1

    async def test_empty_answer_penalizes_candidate_and_fails_over(self) -> None:
        empty = _EmptyBackend()
        good = _FixedLatencyBackend(model="good", delay_ms=1)
        router = LatencyRoutedChatBackend(candidates=[("empty", empty), ("good", good)])

        reply = await router.answer(prompt="hi", view_context={}, history=[])

        assert empty.calls == 1
        assert good.calls == 1
        assert reply["answer"] == "ok"
        assert reply["router"]["reason"] == "failover"

    async def test_empty_stream_fails_over_before_emitting_done(self) -> None:
        empty = _EmptyStreamingBackend()
        good = _StreamingBackend()
        router = LatencyRoutedChatBackend(candidates=[("empty", empty), ("good", good)])

        events = [
            event async for event in router.answer_stream(prompt="hi", view_context={}, history=[])
        ]

        assert empty.calls == 1
        assert good.calls == 1
        assert events[-1]["answer"] == "hello"
        assert events[-1]["router"]["reason"] == "failover"

    async def test_stream_failure_before_first_token_fails_over(self) -> None:
        bad = _StreamingBackend(fail_before=True)
        good = _StreamingBackend()
        router = LatencyRoutedChatBackend(candidates=[("bad", bad), ("good", good)])

        events = [
            event async for event in router.answer_stream(prompt="hi", view_context={}, history=[])
        ]

        assert bad.calls == 1
        assert good.calls == 1
        assert events[0] == {"type": "token", "delta": "hello"}
        assert events[-1]["type"] == "done"
        assert events[-1]["model"] == "good"
        assert events[-1]["router"]["reason"] == "failover"

    async def test_stream_failure_after_first_token_does_not_mix_models(self) -> None:
        bad = _StreamingBackend(fail_after=True)
        good = _StreamingBackend()
        router = LatencyRoutedChatBackend(candidates=[("bad", bad), ("good", good)])
        events: list[dict[str, Any]] = []

        with pytest.raises(RuntimeError, match="failed after token"):
            async for event in router.answer_stream(prompt="hi", view_context={}, history=[]):
                events.append(event)

        assert events == [{"type": "token", "delta": "hello"}]
        assert good.calls == 0


async def _collect_stream(router: LatencyRoutedChatBackend) -> list[dict[str, Any]]:
    return [event async for event in router.answer_stream(prompt="hi", view_context={}, history=[])]


class TestRouterConcurrencyFairness:
    """Concurrent turns during warm-up MUST spread across candidates.

    Without in-flight accounting, N async turns arriving at once all read
    the same "coldest" candidate from ``_pick`` and stampede one backend,
    starving the warm-up rotation.
    """

    async def test_concurrent_warmup_spreads_across_candidates(self) -> None:
        # Each backend sleeps enough that all three warm-up picks are
        # in-flight simultaneously when the next pick happens.
        fast = _FixedLatencyBackend(model="fast", delay_ms=30)
        mid = _FixedLatencyBackend(model="mid", delay_ms=30)
        slow = _FixedLatencyBackend(model="slow", delay_ms=30)
        router = LatencyRoutedChatBackend(
            candidates=[("fast", fast), ("mid", mid), ("slow", slow)],
        )
        # Fire three warm-up picks in parallel.
        await asyncio.gather(
            router.answer(prompt="a", view_context={}, history=[]),
            router.answer(prompt="b", view_context={}, history=[]),
            router.answer(prompt="c", view_context={}, history=[]),
        )
        # Every candidate saw exactly one call - not three on "fast".
        assert fast.calls == 1
        assert mid.calls == 1
        assert slow.calls == 1


class TestRouterCleanup:
    class _WithClient:
        def __init__(self) -> None:
            self.closed = False
            self._http = self  # so getattr(backend, "_http", None) returns it

        async def aclose(self) -> None:
            self.closed = True

        async def answer(
            self,
            *,
            prompt: str,  # noqa: ARG002
            view_context: dict[str, Any],  # noqa: ARG002
            history: list[dict[str, str]],  # noqa: ARG002
        ) -> dict[str, Any]:  # pragma: no cover - unused in this test
            return {"answer": "ok", "model": "x"}

    async def test_aclose_closes_every_candidate_client(self) -> None:
        a = self._WithClient()
        b = self._WithClient()
        router = LatencyRoutedChatBackend(candidates=[("a", a), ("b", b)])
        await router.aclose()
        assert a.closed is True
        assert b.closed is True

    async def test_aclose_tolerates_backends_without_client(self) -> None:
        # A backend that never allocated a client (no ``_http`` attr) must
        # not break the cleanup path.
        a = _FixedLatencyBackend(model="a", delay_ms=1)
        b = _FixedLatencyBackend(model="b", delay_ms=1)
        router = LatencyRoutedChatBackend(candidates=[("a", a), ("b", b)])
        await router.aclose()  # must not raise


class TestRouterBenchmark:
    async def test_benchmark_measures_all_and_returns_fastest(self) -> None:
        from fdai.delivery.operator_api.routes.chat import _ROUTER_WARMUP_SAMPLES

        fast = _FixedLatencyBackend(model="fast", delay_ms=5)
        slow = _FixedLatencyBackend(model="slow", delay_ms=40)
        router = LatencyRoutedChatBackend(candidates=[("fast", fast), ("slow", slow)])
        chose = await router.benchmark()
        # Every candidate was probed enough to clear warm-up, and the fastest
        # (by measured p50) is the pick.
        assert fast.calls == _ROUTER_WARMUP_SAMPLES
        assert slow.calls == _ROUTER_WARMUP_SAMPLES
        assert chose == "fast"
        by_name = {s["deployment"]: s for s in router.stats()}
        assert by_name["fast"]["samples"] == _ROUTER_WARMUP_SAMPLES
        assert by_name["slow"]["samples"] == _ROUTER_WARMUP_SAMPLES

    async def test_benchmark_penalises_a_failing_candidate(self) -> None:
        ok = _FixedLatencyBackend(model="ok", delay_ms=5)
        broken = _RaisingBackend(model="broken")
        router = LatencyRoutedChatBackend(candidates=[("ok", ok), ("broken", broken)])
        chose = await router.benchmark()
        # A failing candidate still records (penalty) samples and never wins.
        assert chose == "ok"
        by_name = {s["deployment"]: s for s in router.stats()}
        assert by_name["broken"]["p50_ms"] is not None
        assert by_name["broken"]["p50_ms"] >= 30_000
        assert describe_backend(router)["available"] is True

    async def test_health_is_unavailable_when_every_candidate_probe_fails(self) -> None:
        first = _RaisingBackend(model="first")
        second = _RaisingBackend(model="second")
        router = LatencyRoutedChatBackend(candidates=[("first", first), ("second", second)])

        await router.benchmark()

        descriptor = describe_backend(router)
        assert descriptor["available"] is False
        assert descriptor["mode"] == "azure-ad-routed-unavailable"
        assert descriptor["model"] is None


class TestCompletionBodyParams:
    def test_classic_models_use_max_tokens_and_temperature(self) -> None:
        from fdai.delivery.operator_api.routes.chat import _completion_body_params

        for model in ("gpt-4o-mini", "gpt-4.1-mini", "gpt-4o"):
            params = _completion_body_params(model, temperature=0.2, max_tokens=800)
            assert params == {"temperature": 0.2, "max_tokens": 800}

    def test_new_models_use_max_completion_tokens_and_no_temperature(self) -> None:
        from fdai.delivery.operator_api.routes.chat import _completion_body_params

        for model in (
            "gpt-5-mini",
            "gpt-5-nano",
            "o3-mini",
            "o4-mini",
            "o1",
            "narrator-gpt-5-4-mini",
            "narrator-gpt-5-mini",
        ):
            params = _completion_body_params(model, temperature=0.2, max_tokens=800)
            assert params == {"max_completion_tokens": 800}
            assert "temperature" not in params

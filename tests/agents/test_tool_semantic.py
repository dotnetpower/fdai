"""Semantic tool selection: it leads, it degrades, and it stays replayable."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence
from dataclasses import replace

import pytest

from fdai.agents._framework.pantheon import PANTHEON_SPECS
from fdai.agents._framework.tool_examples import TOOL_EXAMPLES
from fdai.agents._framework.tool_prefetch import plan_tools
from fdai.agents._framework.tool_semantic import (
    SemanticToolConfig,
    SemanticToolPlanner,
    _ToolVector,
)

pytestmark = pytest.mark.anyio

_DIM = 8


class _KeywordEmbedding:
    """A stand-in whose geometry is decided by declared anchor words.

    Not a language model. Each dimension is one domain, so a text lands
    near the domains it mentions. That is enough to exercise the tier's
    contract - leads, degrades, caches, abstains below the floor - without
    pinning behaviour to a vendor.
    """

    dim = _DIM
    _DOMAINS = (
        ("cost", "spend", "bill", "budget"),
        ("rollback", "undo", "recover"),
        ("approval", "sign", "approve"),
        ("chaos", "experiment", "resilience"),
        ("capacity", "sizing", "headroom", "scale"),
        ("security", "suspicious", "drift"),
        ("audit", "issue", "handover"),
        ("rule", "policy", "candidate"),
    )

    def __init__(self) -> None:
        self.calls = 0

    async def embed(self, text: str) -> list[float]:
        self.calls += 1
        lowered = text.lower()
        vector = [float(sum(word in lowered for word in domain)) for domain in self._DOMAINS]
        if not any(vector):
            vector[0] = 0.01  # never a zero vector; the tier drops those
        return vector


class _BrokenEmbedding:
    dim = _DIM

    async def embed(self, text: str) -> list[float]:
        raise RuntimeError("embedding provider unavailable")


class _WrongDimEmbedding:
    dim = _DIM

    async def embed(self, text: str) -> list[float]:
        return [1.0, 0.0]


def _planner(model: object, **kwargs: object) -> SemanticToolPlanner:
    return SemanticToolPlanner(
        embedding_model=model,  # type: ignore[arg-type]
        specs=PANTHEON_SPECS,
        **kwargs,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# The catalog is a promise the planner keeps.
# ---------------------------------------------------------------------------


def test_every_declared_tool_has_an_example_and_every_example_a_tool() -> None:
    """A tool with no anchor is unreachable; an anchor with no tool misleads."""
    declared = {tool.tool_id for spec in PANTHEON_SPECS for tool in spec.conversation.tool_specs}

    assert set(TOOL_EXAMPLES) == declared


def test_every_example_pair_is_bilingual() -> None:
    """English-only anchors give Korean operators a weaker read path."""
    for tool_id, examples in TOOL_EXAMPLES.items():
        assert len(examples) == 2, tool_id
        english, korean = examples
        assert english.isascii(), tool_id
        assert any("가" <= char <= "힣" for char in korean), tool_id


def test_the_examples_reach_the_declared_tools() -> None:
    """Declared once, attached everywhere: the charter carries them."""
    for spec in PANTHEON_SPECS:
        for tool in spec.conversation.tool_specs:
            assert tool.examples == TOOL_EXAMPLES[tool.tool_id]


# ---------------------------------------------------------------------------
# Selection contract.
# ---------------------------------------------------------------------------


async def test_meaning_selects_a_tool_the_words_would_have_missed() -> None:
    """The reason this tier exists, in one case."""
    question = "how much did we spend"
    planner = _planner(_KeywordEmbedding())

    plans = await planner.plan(question, agents=("Njord",))

    assert plans
    assert plans[0].agent == "Njord"


async def test_a_plan_says_which_tier_chose_it() -> None:
    """An answer must be able to attribute how its evidence was selected."""
    plans = await _planner(_KeywordEmbedding()).plan("rollback", agents=("Vidar",))

    assert plans
    assert plans[0].tier == "t1_semantic"


async def test_distinct_cosines_do_not_become_a_false_integer_tie() -> None:
    """A unique best tool must remain unique after plan serialization."""

    class _CloseEmbedding:
        dim = 2

        async def embed(self, text: str) -> list[float]:
            if "Observed cost samples" in text:
                return [0.804, math.sqrt(1 - 0.804**2)]
            if "Known action cost model" in text:
                return [0.796, math.sqrt(1 - 0.796**2)]
            if text == "query":
                return [1.0, 0.0]
            return [0.0, 1.0]

    njord = next(spec for spec in PANTHEON_SPECS if spec.name == "Njord")
    tools = tuple(
        tool
        for tool in njord.conversation.tool_specs
        if tool.tool_id in {"read_cost_samples", "read_cost_model"}
    )
    spec = replace(
        njord,
        conversation=replace(njord.conversation, tool_specs=tools),
    )
    planner = SemanticToolPlanner(
        embedding_model=_CloseEmbedding(),
        specs=(spec,),
    )

    plans = await planner.plan("query", agents=("Njord",), limit=3)

    assert [plan.tool_id for plan in plans] == ["read_cost_samples", "read_cost_model"]
    assert plans[0].score == pytest.approx(80.4)
    assert plans[1].score == pytest.approx(79.6)
    assert plans[0].score != plans[1].score


async def test_the_same_question_replays_to_the_same_plan() -> None:
    """Tool selection is part of the evidence trail, so it must replay."""
    planner = _planner(_KeywordEmbedding())
    first = await planner.plan("approval waiting", agents=("Var",))

    for _ in range(10):
        assert await planner.plan("approval waiting", agents=("Var",)) == first


async def test_a_plan_never_exceeds_the_cap() -> None:
    planner = _planner(_KeywordEmbedding())

    assert len(await planner.plan("cost budget rollback approval chaos", limit=999)) <= 3


async def test_narrowing_to_an_agent_never_crosses_to_another() -> None:
    plans = await _planner(_KeywordEmbedding()).plan("cost budget", agents=("Njord",))

    assert plans
    assert {plan.agent for plan in plans} == {"Njord"}


async def test_the_tool_catalog_is_embedded_once_and_cached() -> None:
    """A per-question re-embed of 38 tools would price the tier out."""
    model = _KeywordEmbedding()
    planner = _planner(model)

    await planner.plan("cost")
    after_first = model.calls
    await planner.plan("rollback")

    tools = sum(len(spec.conversation.tool_specs) for spec in PANTHEON_SPECS)
    assert after_first == tools + 1
    assert model.calls == after_first + 1


async def test_a_concurrent_first_use_embeds_the_catalog_once() -> None:
    """Eight questions build one cache and only its owner waits for it."""
    model = _KeywordEmbedding()
    planner = _planner(model)

    await asyncio.gather(*[planner.plan("cost") for _ in range(8)])

    tools = sum(len(spec.conversation.tool_specs) for spec in PANTHEON_SPECS)
    # One catalog and one query. The other seven questions see the build
    # in flight and degrade immediately instead of waiting behind it.
    assert model.calls == tools + 1


# ---------------------------------------------------------------------------
# Abstention and degradation. An unsure tier must cost nothing.
# ---------------------------------------------------------------------------


async def test_a_match_below_the_floor_selects_nothing() -> None:
    """Spending a read on a guess is worse than answering without one."""
    planner = _planner(_KeywordEmbedding(), config=SemanticToolConfig(cosine_threshold=0.9))

    # Two unrelated domains at once: no single tool sits near both, so
    # every candidate lands well below the floor.
    assert await planner.plan("cost rollback") == ()


async def test_a_provider_failure_selects_nothing_rather_than_raising() -> None:
    """A read path must not fail because a side-channel did."""
    assert await _planner(_BrokenEmbedding()).plan("cost") == ()


async def test_a_wrong_dimension_vector_is_refused() -> None:
    """A provider that changed shape must not silently score garbage."""
    assert await _planner(_WrongDimEmbedding()).plan("cost") == ()


@pytest.mark.parametrize("value", (float("nan"), float("inf"), -float("inf")))
async def test_a_non_finite_vector_is_never_cached(value: float) -> None:
    """Match the agent router: NaN and Infinity are not embedding coordinates."""

    class _NonFiniteEmbedding:
        dim = _DIM

        async def embed(self, text: str) -> list[float]:
            return [value, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    planner = _planner(_NonFiniteEmbedding())

    assert await planner.plan("cost") == ()
    assert planner._vectors is None


@pytest.mark.parametrize("value", (True, False, "1"))
async def test_a_non_numeric_vector_coordinate_is_never_cached(value: object) -> None:
    class _InvalidCoordinateEmbedding:
        dim = _DIM

        async def embed(self, text: str) -> list[object]:
            return [value, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    planner = _planner(_InvalidCoordinateEmbedding())

    assert await planner.plan("cost") == ()
    assert planner._vectors is None


async def test_an_empty_question_selects_nothing() -> None:
    for question in ("", "   "):
        assert await _planner(_KeywordEmbedding()).plan(question) == ()


async def test_an_oversized_question_never_reaches_the_embedding_provider() -> None:
    """The public prefetch API cannot rely on Bragi's input boundary."""

    model = _KeywordEmbedding()
    planner = _planner(model)

    plans = await plan_tools(
        "x" * 2_001,
        semantic=planner,
        agents=("Njord",),
        limit=3,
    )

    assert plans == ()
    assert model.calls == 0


# ---------------------------------------------------------------------------
# Tier order. Measured: meaning 13/14, lexical 3/14, lexical-first 11/14.
# ---------------------------------------------------------------------------


async def test_meaning_leads_and_a_weak_word_match_cannot_veto_it() -> None:
    """Lexical-first measured worse than meaning alone, so it does not lead.

    'resource' appears in a Freyr fact key, so the lexical tier answers
    this question confidently and wrongly. Meaning must still decide.
    """
    question = "should we scale this up"
    planner = _planner(_KeywordEmbedding())

    plans = await plan_tools(question, semantic=planner, agents=("Freyr",), limit=3)

    assert plans
    assert plans[0].tier == "t1_semantic"


async def test_no_embedding_bound_keeps_exactly_the_lexical_result() -> None:
    """The tier is additive: without it, nothing about today changes."""
    from fdai.agents._framework.tool_planner import plan_conversation_tools

    question = "pending approvals and approval policy"

    assert await plan_tools(
        question, semantic=None, agents=("Var",), limit=3
    ) == plan_conversation_tools(question, agents=("Var",), limit=3)


async def test_a_silent_semantic_abstention_degrades_to_the_words() -> None:
    """Meaning that finds nothing must not erase what the words found."""
    planner = _planner(_KeywordEmbedding(), config=SemanticToolConfig(cosine_threshold=0.9))
    question = "pending approvals cost"

    plans = await plan_tools(question, semantic=planner, agents=("Var",), limit=3)

    assert plans
    assert plans[0].tier == "t0_lexical"


async def test_a_broken_provider_degrades_to_the_words() -> None:
    plans: Sequence[object] = await plan_tools(
        "pending approvals", semantic=_planner(_BrokenEmbedding()), agents=("Var",), limit=3
    )

    assert plans


async def test_a_cancelled_question_does_not_abandon_the_cache_build() -> None:
    """Otherwise the tier is permanently off while permanently costing money.

    Building the cache is one provider round trip per declared tool,
    which under a remote provider outlasts the budget the asking question
    runs under. If the build died with that question, every later
    question would restart it, cancel it again, and pay for the
    embeddings without the cache ever completing.
    """
    from fdai.agents._framework import tool_prefetch as prefetch_module

    class _SlowEmbedding:
        dim = _DIM

        def __init__(self) -> None:
            self.calls = 0

        async def embed(self, text: str) -> list[float]:
            self.calls += 1
            await asyncio.sleep(0.005)
            return [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    model = _SlowEmbedding()
    planner = _planner(
        model,
        config=SemanticToolConfig(retry_cooldown_seconds=0),
    )
    tools = sum(len(spec.conversation.tool_specs) for spec in PANTHEON_SPECS)

    original = prefetch_module.PREFETCH_BUDGET_SECONDS
    prefetch_module.PREFETCH_BUDGET_SECONDS = 0.02
    try:
        # The question gives up on schedule and degrades to the words.
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.02):
                await planner.plan("cost")
    finally:
        prefetch_module.PREFETCH_BUDGET_SECONDS = original

    assert model.calls < tools  # the build really was interrupted mid-way

    # The build survived; it finishes and the next question finds it ready.
    for _ in range(200):
        if planner._vectors is not None:
            break
        await asyncio.sleep(0.01)

    assert planner._vectors is not None
    assert model.calls == tools  # built once, not restarted
    assert await planner.plan("cost")
    assert model.calls == tools + 1


async def test_a_partial_catalog_is_refused_rather_than_cached() -> None:
    """Ranking is relative, so a missing tool sends its questions elsewhere.

    One provider hiccup on one tool would not merely lose that tool; it
    would quietly and permanently rewire every question that belonged to
    it toward whichever tool is next closest, with no signal at all.
    """

    class _OneBadTool:
        dim = _DIM

        def __init__(self) -> None:
            self.fail = True

        async def embed(self, text: str) -> list[float]:
            if self.fail and "rollback" in text.lower():
                return [0.0] * _DIM  # a vector the tier cannot use
            return [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    model = _OneBadTool()
    planner = _planner(
        model,
        config=SemanticToolConfig(retry_cooldown_seconds=0),
    )

    assert await planner.plan("anything") == ()
    assert planner._vectors is None  # nothing cached, so nothing is silently lost

    model.fail = False
    assert await planner.plan("anything")

    tools = sum(len(spec.conversation.tool_specs) for spec in PANTHEON_SPECS)
    assert planner._vectors is not None
    assert len(planner._vectors) == tools


async def test_an_invalid_provider_fails_fast_and_enters_cooldown() -> None:
    """A broken provider must not cost one full catalog per question."""

    class _InvalidEmbedding:
        dim = _DIM

        def __init__(self) -> None:
            self.calls = 0

        async def embed(self, text: str) -> list[float]:
            self.calls += 1
            return [0.0] * _DIM

    model = _InvalidEmbedding()
    planner = _planner(model)

    for _ in range(20):
        assert await planner.plan("cost") == ()

    assert model.calls == 1


def test_retry_cooldown_cannot_be_negative() -> None:
    with pytest.raises(ValueError, match="retry_cooldown_seconds MUST be non-negative"):
        SemanticToolConfig(retry_cooldown_seconds=-0.01)


@pytest.mark.parametrize("value", (float("nan"), float("inf"), -float("inf")))
def test_retry_cooldown_must_be_finite(value: float) -> None:
    with pytest.raises(ValueError, match="retry_cooldown_seconds MUST be non-negative"):
        SemanticToolConfig(retry_cooldown_seconds=value)


@pytest.mark.parametrize("value", (0.0, -1.0, float("nan"), float("inf")))
def test_cache_ttl_must_be_positive_and_finite(value: float) -> None:
    with pytest.raises(ValueError, match="cache_ttl_seconds MUST be positive and finite"):
        SemanticToolConfig(cache_ttl_seconds=value)


@pytest.mark.parametrize("value", (0.0, -1.0, float("nan"), float("inf")))
def test_shutdown_timeout_must_be_positive_and_finite(value: float) -> None:
    with pytest.raises(ValueError, match="shutdown_timeout_seconds MUST be positive and finite"):
        SemanticToolConfig(shutdown_timeout_seconds=value)


@pytest.mark.parametrize("value", (0.0, -1.0, float("nan"), float("inf")))
def test_query_timeout_must_be_positive_and_finite(value: float) -> None:
    with pytest.raises(ValueError, match="query_timeout_seconds MUST be positive and finite"):
        SemanticToolConfig(query_timeout_seconds=value)


@pytest.mark.parametrize(
    "field",
    (
        "cosine_threshold",
        "margin_threshold",
        "retry_cooldown_seconds",
        "cache_ttl_seconds",
        "shutdown_timeout_seconds",
        "query_timeout_seconds",
    ),
)
def test_numeric_config_rejects_boolean_values(field: str) -> None:
    with pytest.raises(ValueError):
        SemanticToolConfig(**{field: True})


@pytest.mark.parametrize(
    "field",
    (
        "cosine_threshold",
        "margin_threshold",
        "retry_cooldown_seconds",
        "cache_ttl_seconds",
        "shutdown_timeout_seconds",
        "query_timeout_seconds",
    ),
)
def test_numeric_config_rejects_overflowing_integer_values(field: str) -> None:
    with pytest.raises(ValueError):
        SemanticToolConfig(**{field: 10**4_000})


async def test_cancellation_resistant_query_is_bounded_and_shared() -> None:
    """A broken query provider leaves at most one task and never holds later callers."""

    class _QueryHangs(_KeywordEmbedding):
        def __init__(self) -> None:
            super().__init__()
            self.release = asyncio.Event()

        async def embed(self, text: str) -> list[float]:
            if text == "query":
                while not self.release.is_set():
                    try:
                        await self.release.wait()
                    except asyncio.CancelledError:
                        continue
                return [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
            return await super().embed(text)

    model = _QueryHangs()
    planner = _planner(
        model,
        config=SemanticToolConfig(
            query_timeout_seconds=0.01,
            shutdown_timeout_seconds=0.01,
        ),
    )

    assert await planner.plan("warm")

    started = asyncio.get_running_loop().time()
    assert await planner.plan("query") == ()
    assert asyncio.get_running_loop().time() - started < 0.1

    calls_after_timeout = model.calls
    for _ in range(25):
        assert await planner.plan("query") == ()
    assert model.calls == calls_after_timeout
    assert planner._query_task is not None
    assert not planner._query_task.done()

    async with asyncio.timeout(0.1):
        await planner.stop()
    assert await planner.plan("warm") == ()

    model.release.set()
    await planner._query_task


async def test_shutdown_is_bounded_when_provider_suppresses_cancellation() -> None:
    """A third-party coroutine cannot hold runtime shutdown forever."""

    class _CancellationResistantEmbedding:
        dim = _DIM

        def __init__(self) -> None:
            self.release = asyncio.Event()
            self.calls = 0

        async def embed(self, text: str) -> list[float]:
            self.calls += 1
            while not self.release.is_set():
                try:
                    await self.release.wait()
                except asyncio.CancelledError:
                    continue
            return [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    model = _CancellationResistantEmbedding()
    planner = _planner(
        model,
        config=SemanticToolConfig(shutdown_timeout_seconds=0.01),
    )

    try:
        async with asyncio.timeout(0.005):
            await planner.plan("cost")
    except TimeoutError:
        pass

    async with asyncio.timeout(0.1):
        await planner.stop()

    calls_at_stop = model.calls
    assert await planner.plan("cost") == ()
    assert model.calls == calls_at_stop

    # Let the deliberately broken provider finish so the test event loop
    # can close; runtime shutdown was already proven to have returned.
    model.release.set()
    assert planner._build_task is not None
    await planner._build_task


async def test_plan_cannot_create_a_build_after_stop_wins_the_race() -> None:
    """The cache boundary must recheck stop after ``plan`` first checked it."""

    entered = asyncio.Event()
    release = asyncio.Event()

    class _PausedPlanner(SemanticToolPlanner):
        async def _tool_vectors(self) -> tuple[_ToolVector, ...]:
            entered.set()
            await release.wait()
            return await super()._tool_vectors()

    model = _KeywordEmbedding()
    planner = _PausedPlanner(embedding_model=model, specs=PANTHEON_SPECS)

    planning = asyncio.create_task(planner.plan("cost"))
    await entered.wait()
    await planner.stop()
    release.set()

    assert await planning == ()
    assert planner._build_task is None
    assert model.calls == 0


async def test_query_boundary_cannot_restart_provider_after_stop() -> None:
    """The query boundary needs the same stop recheck as the cache boundary."""
    model = _KeywordEmbedding()
    planner = _planner(model)

    assert await planner.plan("warm")
    await planner.stop()
    calls_at_stop = model.calls

    assert await planner._query_vector("cost") is None
    assert model.calls == calls_at_stop


async def test_a_plan_names_the_tier_that_selected_it() -> None:
    """The two scores are not comparable, so the tier cannot be inferred."""
    from fdai.agents._framework.tool_planner import plan_conversation_tools

    lexical = plan_conversation_tools("pending approvals", agents=("Var",))
    semantic = await _planner(_KeywordEmbedding()).plan("approval", agents=("Var",))

    assert lexical and semantic
    assert {plan.tier for plan in lexical} == {"t0_lexical"}
    assert {plan.tier for plan in semantic} == {"t1_semantic"}


async def test_a_re_deployed_model_rebuilds_instead_of_ranking_across_spaces() -> None:
    """A truncated dot product is a confident number with no meaning.

    Swap the embedding model and the cached vectors no longer live in the
    same space as a fresh query. Scoring the overlap would keep ranking,
    keep looking certain, and be wrong.
    """

    class _ShiftingDim:
        def __init__(self) -> None:
            self.dim = _DIM
            self.calls = 0

        async def embed(self, text: str) -> list[float]:
            self.calls += 1
            return [1.0] + [0.0] * (self.dim - 1)

    model = _ShiftingDim()
    planner = _planner(model)
    tools = sum(len(spec.conversation.tool_specs) for spec in PANTHEON_SPECS)

    assert await planner.plan("cost")
    assert planner._vectors is not None
    assert len(planner._vectors[0].vector) == _DIM

    model.dim = _DIM // 2
    plans = await planner.plan("cost")

    assert plans
    assert planner._vectors is not None
    assert all(len(entry.vector) == model.dim for entry in planner._vectors)
    assert model.calls == (tools + 1) * 2  # rebuilt, not scored across spaces


async def test_same_dimension_model_swap_is_bounded_by_cache_ttl() -> None:
    """Dimension alone cannot identify an embedding space."""

    class _SameDimSwap:
        dim = _DIM

        def __init__(self) -> None:
            self.calls = 0
            self.space = 0

        async def embed(self, text: str) -> list[float]:
            self.calls += 1
            vector = [0.0] * _DIM
            vector[self.space] = 1.0
            return vector

    model = _SameDimSwap()
    planner = _planner(
        model,
        config=SemanticToolConfig(cache_ttl_seconds=0.01),
    )
    tools = sum(len(spec.conversation.tool_specs) for spec in PANTHEON_SPECS)

    assert await planner.plan("cost")
    assert model.calls == tools + 1

    model.space = 1
    await asyncio.sleep(0.02)
    assert await planner.plan("cost")

    assert model.calls == (tools + 1) * 2
    assert planner._vectors is not None
    assert planner._vectors[0].vector[1] == 1.0

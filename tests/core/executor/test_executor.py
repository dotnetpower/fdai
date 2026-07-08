"""ShadowExecutor - safety-invariant property tests.

Every property this suite asserts corresponds to a rule in
[`.github/instructions/coding-conventions.instructions.md § Safety`]:

- shadow-mode NEVER mutates state - enforce-mode Actions are rejected.
- Every terminal path writes exactly one audit entry.
- Idempotent by ``Action.idempotency_key`` - a re-delivered event
  returns the cached receipt and does NOT republish.
- Blast-radius over the executor cap → abstain + audit.
- Render error → abstain + audit, no PR opened.
- Ordering - actions on the same resource serialize; different
  resources run in parallel.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from fdai.core.executor import (
    ExecutorConfig,
    ExecutorOutcome,
    ResourceLockManager,
    ShadowExecutor,
    TemplateRenderer,
)
from fdai.shared.contracts.models import (
    Action,
    BlastRadius,
    BlastRadiusScope,
    Category,
    CheckLogic,
    CheckLogicKind,
    Mode,
    Operation,
    Provenance,
    Redistribution,
    Remediation,
    RollbackKind,
    RollbackRef,
    Rule,
    RuleSource,
    Severity,
)
from fdai.shared.providers.testing import (
    InMemoryStateStore,
    RecordingRemediationPrPublisher,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
REMEDIATION_ROOT = REPO_ROOT / "rule-catalog" / "remediation"


def _rule() -> Rule:
    return Rule(
        schema_version="1.0.0",
        id="object-storage.owner-tag.required",
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.LOW,
        category=Category.CONFIG_DRIFT,
        resource_type="object-storage",
        check_logic=CheckLogic(
            kind=CheckLogicKind.REGO,
            reference="policies/object_storage/owner_tag_required.rego",
        ),
        remediation=Remediation(
            template_ref="remediation/object_storage/tag_owner.tftpl",
            cost_impact_monthly_usd=0,
        ),
        remediates="remediate.tag-add",
        parameters={"tag_name": "owner", "tag_value": "unknown"},
        provenance=Provenance(
            source_url="https://example.com/rules/x",
            resolved_ref="0" * 40,
            content_hash="sha256:0",
            license="MIT",
            redistribution=Redistribution.EMBEDDABLE,
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
    )


def _action(
    *,
    action_id: str = "00000000-0000-0000-0000-000000000010",
    idempotency_key: str = "example-idem",
    target: str = "resource:example/rg/stg1",
    mode: Mode = Mode.SHADOW,
    count: int | None = 1,
    rate: int | None = 5,
    citing_rules: tuple[str, ...] = ("object-storage.owner-tag.required",),
    params: dict[str, Any] | None = None,
    stop_condition: str = "target_already_tagged",
) -> Action:
    return Action(
        schema_version="1.0.0",
        action_id=action_id,  # type: ignore[arg-type]
        idempotency_key=idempotency_key,
        event_id="00000000-0000-0000-0000-000000000011",  # type: ignore[arg-type]
        action_type="remediate.tag-add",
        target_resource_ref=target,
        operation=Operation.TAG,
        params=params or {"tag_value": "team-a"},
        stop_condition=stop_condition,
        rollback_ref=RollbackRef(kind=RollbackKind.PR_REVERT, reference="pr-99"),
        blast_radius=BlastRadius(
            scope=BlastRadiusScope.RESOURCE, count=count, rate_per_minute=rate
        ),
        mode=mode,
        citing_rules=list(citing_rules),
        created_at="2026-07-05T08:00:00Z",  # type: ignore[arg-type]
    )


def _executor(
    **overrides: Any,
) -> tuple[
    ShadowExecutor,
    RecordingRemediationPrPublisher,
    InMemoryStateStore,
]:
    publisher = RecordingRemediationPrPublisher()
    audit = InMemoryStateStore()
    executor = ShadowExecutor(
        publisher=publisher,
        audit_store=audit,
        renderer=TemplateRenderer(remediation_root=REMEDIATION_ROOT),
        resource_lock=ResourceLockManager(),
        config=ExecutorConfig(**overrides) if overrides else None,
    )
    return executor, publisher, audit


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publishes_shadow_pr_and_writes_audit() -> None:
    executor, publisher, audit = _executor()
    result = await executor.execute(action=_action(), rule=_rule())

    assert result.outcome is ExecutorOutcome.PUBLISHED
    assert result.mode is Mode.SHADOW
    assert result.pr_ref is not None

    assert len(publisher.records) == 1
    pr = publisher.records[0]
    assert pr.mode is Mode.SHADOW
    assert "shadow" in pr.labels
    assert "rule:object-storage.owner-tag.required" in pr.labels
    assert "public_network" not in pr.body  # tag rule, not public-access rule
    assert '"owner" = "team-a"' in pr.patch

    entries = list(audit.audit_entries)
    assert len(entries) == 1
    assert entries[0]["entry"]["outcome"] == "published"
    assert entries[0]["entry"]["mode"] == "shadow"


# ---------------------------------------------------------------------------
# Shadow-mode invariant (property)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enforce_mode_action_is_rejected_without_mutation() -> None:
    executor, publisher, audit = _executor()
    result = await executor.execute(action=_action(mode=Mode.ENFORCE), rule=_rule())
    assert result.outcome is ExecutorOutcome.REJECTED_MODE
    assert result.mode is Mode.SHADOW
    assert result.pr_ref is None
    assert publisher.records == ()
    assert len(list(audit.audit_entries)) == 1


@pytest.mark.asyncio
async def test_every_terminal_path_writes_exactly_one_audit_entry() -> None:
    """Property: audit count == number of execute() calls, in every branch."""
    render_error_rule = Rule(
        schema_version="1.0.0",
        id="compute.vm-scale-set.over-provisioned",
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.MEDIUM,
        category=Category.COST,
        resource_type="compute.vm-scale-set",
        check_logic=CheckLogic(kind=CheckLogicKind.REGO, reference="policies/x.rego"),
        remediation=Remediation(template_ref="remediation/compute/vmss_right_size.tftpl"),
        remediates="remediate.right-size",
        parameters={},
        provenance=Provenance(
            source_url="https://example.com/rules/x",
            resolved_ref="0" * 40,
            content_hash="sha256:0",
            license="MIT",
            redistribution=Redistribution.EMBEDDABLE,
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
    )
    cases: list[tuple[Any, Rule]] = [
        (_action(idempotency_key="k1"), _rule()),  # published
        (
            _action(mode=Mode.ENFORCE, idempotency_key="k2"),
            _rule(),
        ),  # rejected mode
        (_action(count=10_000, idempotency_key="k3"), _rule()),  # blast radius
        (
            _action(
                idempotency_key="k4",
                citing_rules=("compute.vm-scale-set.over-provisioned",),
                params={},
            ),
            render_error_rule,
        ),  # render error
    ]
    for action, rule in cases:
        executor, publisher, audit = _executor()
        await executor.execute(action=action, rule=rule)
        assert len(list(audit.audit_entries)) == 1


# ---------------------------------------------------------------------------
# Blast-radius enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blast_radius_over_count_cap_abstains() -> None:
    executor, publisher, audit = _executor(max_affected_resources=5)
    result = await executor.execute(action=_action(count=10, idempotency_key="k1"), rule=_rule())
    assert result.outcome is ExecutorOutcome.ABSTAINED_BLAST_RADIUS
    assert result.reason is not None
    assert "blast-radius count 10" in result.reason
    assert publisher.records == ()


@pytest.mark.asyncio
async def test_blast_radius_over_rate_cap_abstains() -> None:
    executor, publisher, _ = _executor(max_rate_per_minute=1)
    result = await executor.execute(action=_action(rate=10, idempotency_key="k1"), rule=_rule())
    assert result.outcome is ExecutorOutcome.ABSTAINED_BLAST_RADIUS
    assert publisher.records == ()


@pytest.mark.asyncio
async def test_blast_radius_at_cap_is_allowed() -> None:
    executor, publisher, _ = _executor(max_affected_resources=5)
    result = await executor.execute(action=_action(count=5, idempotency_key="k1"), rule=_rule())
    assert result.outcome is ExecutorOutcome.PUBLISHED
    assert publisher.records != ()


# ---------------------------------------------------------------------------
# Render failure fail-close
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_render_error_abstains_and_does_not_publish() -> None:
    """A template whose required placeholder is missing on BOTH the rule
    and the action MUST abstain - the executor never emits a partial
    patch and never opens a PR."""
    executor, publisher, _ = _executor()

    # Build a rule pointed at the right-size template but with NO
    # parameter defaults, so `target_capacity` is unresolvable.
    right_size_rule = Rule(
        schema_version="1.0.0",
        id="compute.vm-scale-set.over-provisioned",
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.MEDIUM,
        category=Category.COST,
        resource_type="compute.vm-scale-set",
        check_logic=CheckLogic(
            kind=CheckLogicKind.REGO,
            reference="policies/compute/vmss_over_provisioned.rego",
        ),
        remediation=Remediation(template_ref="remediation/compute/vmss_right_size.tftpl"),
        remediates="remediate.right-size",
        parameters={},  # explicit: no defaults for the placeholders below
        provenance=Provenance(
            source_url="https://example.com/rules/x",
            resolved_ref="0" * 40,
            content_hash="sha256:0",
            license="MIT",
            redistribution=Redistribution.EMBEDDABLE,
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
    )
    result = await executor.execute(
        action=_action(
            idempotency_key="k1",
            citing_rules=("compute.vm-scale-set.over-provisioned",),
            params={},  # no target_capacity → render error
        ),
        rule=right_size_rule,
    )
    assert result.outcome is ExecutorOutcome.ABSTAINED_RENDER_ERROR
    assert publisher.records == ()


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_delivery_of_same_key_is_deduped() -> None:
    executor, publisher, audit = _executor()
    a = _action(idempotency_key="dup-key")
    first = await executor.execute(action=a, rule=_rule())
    second = await executor.execute(action=a, rule=_rule())

    assert first.outcome is ExecutorOutcome.PUBLISHED
    assert second is first  # cached
    # publisher saw ONE record; audit saw ONE entry.
    assert len(publisher.records) == 1
    assert len(list(audit.audit_entries)) == 1


@pytest.mark.asyncio
async def test_publisher_reports_already_existed_after_process_restart() -> None:
    """Simulate a restart by reusing the publisher (persistent) with a
    fresh executor (empty dedupe cache)."""
    publisher = RecordingRemediationPrPublisher()
    audit_a = InMemoryStateStore()
    audit_b = InMemoryStateStore()
    action = _action(idempotency_key="cross-restart")

    exec_a = ShadowExecutor(
        publisher=publisher,
        audit_store=audit_a,
        renderer=TemplateRenderer(remediation_root=REMEDIATION_ROOT),
        resource_lock=ResourceLockManager(),
    )
    result_a = await exec_a.execute(action=action, rule=_rule())
    assert result_a.outcome is ExecutorOutcome.PUBLISHED

    exec_b = ShadowExecutor(
        publisher=publisher,
        audit_store=audit_b,
        renderer=TemplateRenderer(remediation_root=REMEDIATION_ROOT),
        resource_lock=ResourceLockManager(),
    )
    result_b = await exec_b.execute(action=action, rule=_rule())
    assert result_b.outcome is ExecutorOutcome.ALREADY_EXISTED
    # New executor writes its own audit entry with the ALREADY_EXISTED outcome.
    entries = list(audit_b.audit_entries)
    assert len(entries) == 1
    assert entries[0]["entry"]["outcome"] == "already_existed"


@pytest.mark.asyncio
async def test_durable_idempotency_skips_publisher_after_restart() -> None:
    """With a durable idempotency store, a post-restart re-delivery returns
    the recorded result WITHOUT re-calling the publisher - no double
    mutation even when the publisher is not itself idempotent."""
    from fdai.shared.providers.testing.idempotency import InMemoryIdempotencyStore

    store = InMemoryIdempotencyStore()  # survives the simulated restart
    action = _action(idempotency_key="durable-key")

    pub_a = RecordingRemediationPrPublisher()
    exec_a = ShadowExecutor(
        publisher=pub_a,
        audit_store=InMemoryStateStore(),
        renderer=TemplateRenderer(remediation_root=REMEDIATION_ROOT),
        resource_lock=ResourceLockManager(),
        idempotency=store,
    )
    result_a = await exec_a.execute(action=action, rule=_rule())
    assert result_a.outcome is ExecutorOutcome.PUBLISHED
    assert len(pub_a.records) == 1

    # Restart: fresh executor AND fresh (non-idempotent) publisher, same
    # durable store.
    pub_b = RecordingRemediationPrPublisher()
    exec_b = ShadowExecutor(
        publisher=pub_b,
        audit_store=InMemoryStateStore(),
        renderer=TemplateRenderer(remediation_root=REMEDIATION_ROOT),
        resource_lock=ResourceLockManager(),
        idempotency=store,
    )
    result_b = await exec_b.execute(action=action, rule=_rule())
    assert result_b.outcome is ExecutorOutcome.PUBLISHED  # returned from the store
    assert len(pub_b.records) == 0  # publisher NEVER called - no double mutation


# ---------------------------------------------------------------------------
# Ordering (per-resource lock)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_actions_on_same_resource_are_serialized() -> None:
    """Two actions on one resource → they never observe each other mid-flight."""
    executor, publisher, _ = _executor()
    # Kick off concurrent executes; the second one waits for the lock.
    tasks = [
        executor.execute(
            action=_action(idempotency_key=f"k-{i}", target="same"),
            rule=_rule(),
        )
        for i in range(3)
    ]
    results = await asyncio.gather(*tasks)
    assert {r.outcome for r in results} == {ExecutorOutcome.PUBLISHED}
    assert len(publisher.records) == 3


# ---------------------------------------------------------------------------
# Audit content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_entry_captures_every_safety_invariant() -> None:
    """The audit record MUST contain the four invariants + citing rules."""
    executor, _, audit = _executor()
    await executor.execute(action=_action(), rule=_rule())
    (record,) = list(audit.audit_entries)
    entry = record["entry"]
    for field in (
        "stop_condition",
        "rollback_kind",
        "rollback_reference",
        "blast_radius",
        "citing_rule_ids",
        "mode",
    ):
        assert field in entry, f"missing audit field: {field}"
    assert entry["mode"] == "shadow"
    assert entry["citing_rule_ids"] == ["object-storage.owner-tag.required"]


@pytest.mark.asyncio
async def test_audit_records_form_a_hash_chain() -> None:
    """InMemoryStateStore mimics the production hash-chain contract."""
    executor, _, audit = _executor()
    for i in range(3):
        await executor.execute(action=_action(idempotency_key=f"k-{i}"), rule=_rule())
    assert audit.verify_chain(), "audit chain broken"


# ---------------------------------------------------------------------------
# Defensive safety-invariant guard (defense-in-depth against non-pydantic callers)
# ---------------------------------------------------------------------------


def test_missing_safety_invariant_helper_covers_every_branch() -> None:
    """The pydantic Action model already requires these fields; the helper is
    defense-in-depth for a caller that bypasses validation (a fork wiring
    a fake, a manual composition test). Exercise every branch via a plain
    attribute stub so a future refactor cannot silently drop a check.
    """
    from types import SimpleNamespace

    from fdai.core.executor.executor import _missing_safety_invariant

    def _stub(**overrides: Any) -> Any:
        defaults: dict[str, Any] = {
            "stop_condition": "ok",
            "rollback_ref": SimpleNamespace(kind="pr_revert", reference=None),
            "blast_radius": SimpleNamespace(scope="resource", count=1),
            "citing_rules": ["r1"],
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    # Happy path
    assert _missing_safety_invariant(_stub()) is None
    # Blank stop_condition
    reason = _missing_safety_invariant(_stub(stop_condition="   "))
    assert reason is not None and "stop_condition" in reason
    # No rollback kind
    bad_rollback = SimpleNamespace(kind=None, reference=None)
    reason = _missing_safety_invariant(_stub(rollback_ref=bad_rollback))
    assert reason is not None and "rollback_ref" in reason
    # blast_radius=None
    reason = _missing_safety_invariant(_stub(blast_radius=None))
    assert reason is not None and "blast_radius" in reason
    # Empty citing_rules
    reason = _missing_safety_invariant(_stub(citing_rules=[]))
    assert reason is not None and "citing_rules" in reason


@pytest.mark.asyncio
async def test_dedupe_cache_evicts_oldest_entry_when_over_cap() -> None:
    """FIFO eviction: when the dedupe cap is reached the oldest key is
    dropped so `_dedupe` cannot grow unbounded across a long-running
    process. A retry that arrives after eviction re-enters the executor
    (its L1 dedup does not short-circuit) but the persistent publisher
    still recognizes the key and returns ``already_existed`` - which is
    exactly how a real cross-restart retry would look."""

    executor, publisher, _audit = _executor(max_dedupe_entries=2)

    # Three distinct keys - the third insertion evicts the first from
    # the L1 dedup cache.
    for key in ("evict-a", "evict-b", "evict-c"):
        await executor.execute(action=_action(idempotency_key=key), rule=_rule())

    assert list(executor._dedupe.keys()) == ["evict-b", "evict-c"]

    # The first key was evicted from L1, so a retry re-enters the
    # executor path (not a cache short-circuit). The publisher's
    # `_by_key` ledger persists so it reports the retry as
    # ``already_existed`` - the ExecutionResult still surfaces the
    # ALREADY_EXISTED outcome distinct from PUBLISHED.
    retry = await executor.execute(
        action=_action(idempotency_key="evict-a"), rule=_rule()
    )
    assert retry.outcome is ExecutorOutcome.ALREADY_EXISTED

    # After the retry, the newly touched key sits at the tail of the
    # ordered dict and the previously-oldest survivor was evicted.
    assert list(executor._dedupe.keys()) == ["evict-c", "evict-a"]


@pytest.mark.asyncio
async def test_audit_failure_does_not_poison_dedupe_cache() -> None:
    """Cache-poisoning regression: if the audit write raises (DB down,
    network partition) the L1 dedup cache MUST NOT keep the result. A
    retry after audit failure has to re-execute so the durable trail
    catches up. This is the reason ``_write_audit`` runs BEFORE
    ``_remember`` in :meth:`ShadowExecutor._finish`."""

    class _RaisingAuditStore:
        """Minimal ``StateStore`` fake that raises on every append."""

        async def append_audit_entry(self, entry: Mapping[str, Any]) -> None:
            raise RuntimeError("audit store unavailable (simulated)")

        async def append_incident_transition(self, entry: Mapping[str, Any]) -> None:
            raise RuntimeError("audit store unavailable (simulated)")

    publisher = RecordingRemediationPrPublisher()
    executor = ShadowExecutor(
        publisher=publisher,
        audit_store=_RaisingAuditStore(),  # type: ignore[arg-type]
        renderer=TemplateRenderer(remediation_root=REMEDIATION_ROOT),
        resource_lock=ResourceLockManager(),
    )

    with pytest.raises(RuntimeError, match="audit store unavailable"):
        await executor.execute(
            action=_action(idempotency_key="poison-test"), rule=_rule()
        )

    # Cache MUST NOT carry the failed key - a retry would otherwise
    # short-circuit past the audit path and never persist the record.
    assert "poison-test" not in executor._dedupe

"""Local dev entrypoint for the console read API.

Boots the Starlette app with :class:`UnsafeClaimsExtractor` (dev-only
JWT decoder) and an :class:`InMemoryConsoleReadModel` seeded with a few
synthetic entries so the console has something to render.

**Never wire this in production.** The env-var tripwire in
:func:`fdai.delivery.read_api.main.build_app` refuses to build a
dev-mode app unless ``FDAI_READ_API_DEV_MODE=1`` is set - this
module also asserts that at build time so a stray production revision
that boots it fails fast.

Usage (uvicorn's ``--factory`` flag calls :func:`app` at server start,
so importing this module during unrelated tooling - pytest collection,
mypy, IDE indexing - has no side effect)::

    FDAI_READ_API_DEV_MODE=1 \\
        uv run uvicorn 'fdai.delivery.read_api._local:app' \\
            --factory --port 8000
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from starlette.applications import Starlette

# Dev harness: make our own INFO logs visible so live-stream open/close
# events show up alongside uvicorn's access log.
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s: %(message)s")

from fdai.core.audit.what_if_replay import WhatIfEvaluator  # noqa: E402
from fdai.core.measurement.promotion_gate import (  # noqa: E402
    InMemoryShadowVerdictSource,
    ShadowVerdictRecord,
)
from fdai.core.rbac.resolver import GroupMapping, RoleResolver  # noqa: E402
from fdai.core.risk_gate.blast_radius_simulator import (  # noqa: E402
    InMemoryOntologyGraph,
    OntologyGraph,
)
from fdai.core.tiers.t0_deterministic.opa_evaluator import (  # noqa: E402
    MissingOpaBinaryError,
)
from fdai.delivery.read_api.auth import (  # noqa: E402
    UnsafeClaimsExtractor,
    build_authenticator,
)
from fdai.delivery.read_api.live_control_loop import (  # noqa: E402
    ControlLoopEmitterUnavailable,
    build_control_loop_emitter,
)
from fdai.delivery.read_api.live_stream import (  # noqa: E402
    LiveEmitter,
    LiveStreamConfig,
    SyntheticLiveEmitter,
)
from fdai.delivery.read_api.main import ReadApiConfig, build_app  # noqa: E402
from fdai.delivery.read_api.read_model import (  # noqa: E402
    HilQueueItem,
    InMemoryConsoleReadModel,
)
from fdai.delivery.read_api.rule_fire_trace_reader import (  # noqa: E402
    ConsoleReadModelTraceReader,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog  # noqa: E402
from fdai.rule_catalog.schema.link_type import load_link_type_catalog  # noqa: E402
from fdai.rule_catalog.schema.object_type import load_object_type_catalog  # noqa: E402
from fdai.rule_catalog.schema.resource_type import (  # noqa: E402
    load_resource_type_registry_from_mapping,
)
from fdai.rule_catalog.schema.rule import load_rule_catalog  # noqa: E402
from fdai.shared.contracts.models import Rule  # noqa: E402
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry  # noqa: E402
from fdai.shared.providers.sse import SseSink  # noqa: E402
from fdai.shared.providers.testing.sse import InMemorySseSink  # noqa: E402

_DEV_ENV = "FDAI_READ_API_DEV_MODE"
_REPO_ROOT = Path(__file__).resolve().parents[4]

# One seed audit row: (agent, tier, action_kind, outcome, finished_hhmmss,
# correlation, summary, detail, work_ms, inputs, outputs).
_SeedRow = tuple[
    str, str, str, str, str, str, str, str, int, dict[str, str], dict[str, str]
]


def _seed(read_model: InMemoryConsoleReadModel) -> None:
    """Seed audit entries (with trust tiers) + one pending HIL so the SPA renders data.

    Each entry is attributed to the pantheon agent that produced it
    (``actor`` == ``producer_principal``) so the agent-activity waterfall
    can reconstruct "which agent did what, when, and how". Beyond the
    terminal decision, every row carries a lifecycle trace - when the
    upstream event was emitted (``event_ts``), when this agent received it
    (``received_at``), when work began (``started_at``) and finished
    (``finished_at`` == ``recorded_at``), plus ``duration_ms`` / ``queue_ms``
    and structured ``inputs`` / ``outputs`` / ``detail`` - so the console
    detail pane can show the full send -> receive -> work -> record span.
    The tier / outcome / mode split stays realistic (T0-heavy) so the KPI
    dashboard keeps rendering a plausible distribution from the same rows.
    """
    # (agent, tier, action_kind, outcome, finished_hhmmss, correlation,
    #  summary, detail, work_ms, inputs, outputs)
    entries: tuple[_SeedRow, ...] = (
        ("Huginn", "t0", "event.ingest", "normalized", "10:00:00", "corr-a",
         "Normalized 1 Activity Log event into a finding",
         "Consumed 1 Azure Activity Log record for vm-1, deduplicated it against "
         "the 5-minute correlation window, and emitted normalized finding "
         "fnd-0001 (category=security) onto the event bus for the trust router.",
         180,
         {"source": "azure.activity_log", "events_in": "1",
          "resource": "vm-1 (compute.vm)", "region": "eastus"},
         {"finding_id": "fnd-0001", "category": "security",
          "severity": "medium", "deduplicated": "0"}),
        ("Heimdall", "t0", "anomaly.detect", "within_threshold", "10:02:00", "corr-a",
         "Metric anomaly check: no deviation over threshold",
         "Scored the vm-1 metric window against the learned baseline; the "
         "z-score (0.7) stayed under the 3.0 alert threshold, so no anomaly "
         "finding was raised - detection ran in shadow and only logged.",
         220,
         {"finding_id": "fnd-0001", "metric": "cpu_credits_remaining",
          "window": "5m", "baseline": "learned-v3"},
         {"z_score": "0.7", "threshold": "3.0", "anomaly": "false"}),
        ("Forseti", "t0", "verdict.issue", "auto", "10:05:00", "corr-a",
         "Deterministic rule matched; verdict=auto",
         "Matched finding fnd-0001 to rule azure-encryption-at-rest-001 (exact, "
         "confidence 1.0). Single-rule match, low blast radius -> verdict=auto. "
         "No LLM tier was invoked; grounded on the rule citation only.",
         340,
         {"finding_id": "fnd-0001", "rule": "azure-encryption-at-rest-001",
          "match": "exact", "confidence": "1.0"},
         {"verdict": "auto", "risk": "low", "citations": "1"}),
        ("Thor", "t0", "enable-encryption", "shadow_pr_opened", "10:06:00", "corr-a",
         "Opened remediation PR to enable encryption at rest",
         "Rendered the Terraform diff to enable encryption at rest on vm-1's "
         "OS disk, ran what-if (no destructive change), and opened remediation "
         "PR #482 in shadow mode. The PR is the audit + rollback surface; "
         "nothing was applied to the live resource.",
         1200,
         {"verdict": "auto", "resource": "vm-1", "change": "encryption_at_rest=on",
          "delivery": "pr_native"},
         {"pr": "#482", "what_if": "no_destructive_change",
          "mode": "shadow", "applied": "false"}),
        ("Saga", "t0", "audit.record", "recorded", "10:06:30", "corr-a",
         "Appended terminal decision to the audit log",
         "Sealed the corr-a chain: appended the terminal decision as an "
         "append-only, hash-linked audit row (entry_hash over the prior hash) "
         "so the incident is deterministically replayable.",
         90,
         {"correlation": "corr-a", "terminal": "shadow_pr_opened", "steps": "4"},
         {"audit_seq": "recorded", "hash_linked": "true"}),
        ("Njord", "t0", "cost.anomaly", "finding_raised", "10:12:00", "corr-b",
         "Idle public endpoint flagged for cost review",
         "A daily cost probe found public endpoint pe-9 billing with near-zero "
         "traffic for 14 days. Raised cost finding fnd-0002 (est. saving "
         "$38/mo) for the trust router to judge.",
         260,
         {"probe": "cost.idle_endpoint", "resource": "pe-9 (network.public_ip)",
          "idle_days": "14", "traffic": "~0"},
         {"finding_id": "fnd-0002", "est_saving_usd_month": "38",
          "category": "cost"}),
        ("Forseti", "t0", "verdict.issue", "auto", "10:13:00", "corr-b",
         "Cost rule matched; verdict=auto (shadow)",
         "Matched fnd-0002 to rule cost-idle-public-endpoint-004 (exact). Low "
         "blast radius, reversible -> verdict=auto, but the action ships in "
         "shadow until the promotion gate clears.",
         300,
         {"finding_id": "fnd-0002", "rule": "cost-idle-public-endpoint-004",
          "match": "exact", "confidence": "1.0"},
         {"verdict": "auto", "risk": "low", "default_mode": "shadow"}),
        ("Thor", "t0", "close-idle-endpoint", "shadow_pr_opened", "10:14:00", "corr-b",
         "Opened remediation PR to close idle endpoint",
         "Rendered the Terraform diff to deallocate public endpoint pe-9, ran "
         "what-if (reversible via pr_revert), and opened remediation PR #483 in "
         "shadow mode. Rollback contract: pr_revert.",
         1100,
         {"verdict": "auto", "resource": "pe-9", "change": "deallocate",
          "delivery": "pr_native"},
         {"pr": "#483", "rollback": "pr_revert", "mode": "shadow",
          "applied": "false"}),
        ("Freyr", "t0", "capacity.forecast", "forecast_ok", "10:20:00", "corr-c",
         "7-day capacity forecast within headroom",
         "Projected 7-day capacity for the aks-prod node pool from the trailing "
         "28-day trend. Peak projected utilization 62% stays under the 80% "
         "headroom target, so no scale action was proposed.",
         500,
         {"scope": "aks-prod/nodepool-1", "horizon": "7d", "trend_window": "28d"},
         {"projected_peak": "62%", "headroom_target": "80%", "action": "none"}),
        ("Muninn", "t1", "similarity.recall", "matched_prior", "10:42:00", "corr-d",
         "Recalled a resolved incident with 0.91 similarity",
         "Embedded the new finding and searched the incident memory (pgvector). "
         "Nearest resolved incident inc-2041 scored 0.91 cosine, over the 0.85 "
         "reuse threshold - handed the match to Norns for action reuse (T1).",
         150,
         {"finding_id": "fnd-0003", "index": "incident_memory",
          "metric": "cosine", "threshold": "0.85"},
         {"match": "inc-2041", "score": "0.91", "tier": "T1"}),
        ("Norns", "t1", "reuse-learned-action", "shadow_pr_opened", "10:43:00", "corr-d",
         "Reused a learned action from the matched incident",
         "Adapted the learned remediation from inc-2041 to the current resource, "
         "re-validated it against policy-as-code (pass), and opened PR #484 in "
         "shadow. Reuse avoided a T2 model call.",
         800,
         {"source_incident": "inc-2041", "score": "0.91",
          "verifier": "policy_as_code"},
         {"pr": "#484", "verifier": "pass", "mode": "shadow",
          "llm_calls_saved": "1"}),
        ("Odin", "t2", "arbitrate.cross-vertical", "resolved", "10:54:00", "corr-e",
         "Arbitrated resilience-vs-cost conflict before verdict",
         "Two verticals proposed opposing actions on aks-prod (resilience: scale "
         "up; cost: scale down). Odin arbitrated using the cross-vertical policy "
         "and resolved in favour of resilience during the change-freeze window.",
         640,
         {"conflict": "resilience_vs_cost", "resource": "aks-prod",
          "proposals": "2"},
         {"winner": "resilience", "reason": "change_freeze_window",
          "handoff": "Forseti"}),
        ("Forseti", "t2", "root-cause-reasoning", "escalated_hil", "10:55:00", "corr-e",
         "Novel case: mixed-model cross-check disagreed; escalated to HIL",
         "Novel case (no rule, similarity below threshold) routed to T2. The "
         "two cross-check models disagreed on root cause (model-a: throttling; "
         "model-b: node pressure), so the quality gate refused to auto-resolve "
         "and escalated to human-in-the-loop.",
         2100,
         {"tier": "T2", "models": "2", "grounding": "required"},
         {"agreement": "false", "model_a": "throttling",
          "model_b": "node_pressure", "decision": "escalate_hil"}),
        ("Var", "t2", "hil.await", "awaiting_approval", "10:55:30", "corr-e",
         "High-risk action queued for a human approver",
         "Registered the escalated action in the HIL queue for a distinct human "
         "approver (no self-approval). It stays parked - no execution - until an "
         "operator approves or the request times out to a no-op.",
         70,
         {"action": "restrict-network-access", "risk": "high",
          "approver_role": "sre-oncall"},
         {"queue": "hil", "state": "awaiting_approval", "self_approval": "blocked"}),
    )
    base_day = "2026-07-06T"
    # transit (event_ts -> received) and scheduling (received -> started) delays.
    transit_ms = 40
    queue_ms = 80
    prev_finish_by_corr: dict[str, datetime] = {}
    for i, row in enumerate(entries, start=1):
        (agent, tier, action_kind, outcome, hhmmss, correlation, summary,
         detail, work_ms, inputs, outputs) = row
        finished = datetime.fromisoformat(f"{base_day}{hhmmss}+00:00")
        started = finished - timedelta(milliseconds=work_ms)
        received = started - timedelta(milliseconds=queue_ms)
        # event_ts = when the upstream producer emitted what this agent consumed:
        # the previous agent's finish in the same incident, else shortly before
        # this agent received it (the source signal arriving).
        sent = prev_finish_by_corr.get(
            correlation, received - timedelta(milliseconds=transit_ms)
        )
        prev_finish_by_corr[correlation] = finished
        read_model.record_audit_entry(
            {
                "event_id": f"00000000-0000-0000-0000-{i:012d}",
                "correlation_id": correlation,
                "actor": agent,
                "producer_principal": agent,
                "action_kind": action_kind,
                "mode": "shadow",
                "outcome": outcome,
                "tier": tier,
                "summary": summary,
                "detail": detail,
                "event_ts": sent.isoformat(),
                "received_at": received.isoformat(),
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat(),
                "duration_ms": work_ms,
                "queue_ms": queue_ms,
                "inputs": inputs,
                "outputs": outputs,
                "recorded_at": finished.isoformat(),
            }
        )
    read_model.record_hil_pending(
        HilQueueItem(
            idempotency_key="hil-dev-0001",
            event_id="00000000-0000-0000-0000-000000000010",
            action_kind="restrict-network-access",
            reason="blast-radius exceeds executor cap",
            requested_at="2026-07-06T10:10:00+00:00",
            correlation_id="corr-dev-0001",
        )
    )
    _seed_trace(read_model, "corr-dev-0001")


def _seed_trace(read_model: InMemoryConsoleReadModel, correlation: str) -> None:
    """Seed a full pipeline trace under ``correlation`` so the trace / bitemporal
    / what-if routes have a rich sample record to render."""
    base = datetime(2026, 7, 6, 10, 10, 0, tzinfo=UTC)
    steps: tuple[dict[str, Any], ...] = (
        {
            "pipeline_stage": "event_ingest",
            "action_kind": "event.received",
            "payload": {
                "resource": {
                    "resource_id": "vm-1",
                    "type": "compute.vm",
                    "props": {"tier": "S1", "region": "eastus"},
                }
            },
            "state": {"tier": "S1"},
            "effective_at": base.isoformat(),
        },
        {
            "pipeline_stage": "L1_evaluate",
            "action_kind": "trust_router.route",
            "decision": "match",
            "reason": "public_access_enabled",
        },
        {
            "pipeline_stage": "risk_gate",
            "action_kind": "risk_gate.evaluate",
            "decision": "escalate_hil",
            "reason": "blast-radius exceeds executor cap",
            "state": {"tier": "S2", "region": "eastus"},
            "effective_at": (base + timedelta(minutes=5)).isoformat(),
        },
        {
            "pipeline_stage": "escalate",
            "action_kind": "restrict-network-access",
            "decision": "hil_pending",
            "reason": "awaiting human approval",
            "mode": "shadow",
        },
    )
    for offset, entry in enumerate(steps):
        entry_copy = dict(entry)
        entry_copy["correlation_id"] = correlation
        entry_copy["recorded_at"] = (base + timedelta(seconds=offset)).isoformat()
        read_model.record_audit_entry(entry_copy)


def _synthetic_verdicts() -> list[ShadowVerdictRecord]:
    """A demo distribution: some reviewed-and-agreed, one policy escape."""
    now = datetime.now(tz=UTC)
    verdicts: list[ShadowVerdictRecord] = []
    for offset in range(30):
        verdicts.append(
            ShadowVerdictRecord(
                action_type_name="ops.publish-change-summary",
                observed_at=now - timedelta(days=15 + offset % 3),
                was_policy_escape=False,
                operator_reviewed=True,
                operator_agreed=True,
            )
        )
    verdicts.append(
        ShadowVerdictRecord(
            action_type_name="remediate.disable-public-access",
            observed_at=now - timedelta(days=1),
            was_policy_escape=True,
            operator_reviewed=True,
            operator_agreed=False,
        )
    )
    return verdicts


def _build_blast_radius_graph() -> OntologyGraph:
    """Small synthetic graph so the console's simulator has something to render."""
    return InMemoryOntologyGraph(
        edges={
            ("sub-dev", "contains"): ("rg-alpha", "rg-beta"),
            ("rg-alpha", "contains"): ("vnet-alpha", "vm-1"),
            ("vnet-alpha", "contains"): ("subnet-alpha",),
            ("subnet-alpha", "contains"): ("vm-1", "vm-2"),
            ("rg-beta", "contains"): ("stg-beta",),
            ("vm-1", "depends_on"): ("stg-beta", "kv-shared"),
            ("vm-2", "depends_on"): ("kv-shared",),
        },
        link_types=frozenset({"contains", "depends_on", "attached_to"}),
    )


class _DemoTighterTagsEvaluator:
    """Toy :class:`WhatIfEvaluator` for the dev harness.

    Denies whenever the reconstructed event's props do not carry an
    ``owner`` tag, so a fork engineer can eyeball the what-if diff
    against the shipped rules that already deny on the same property.
    """

    def evaluate(
        self, resource_type: str, resource_props: Mapping[str, Any]
    ) -> Sequence[Mapping[str, Any]]:
        del resource_type  # this scenario is type-agnostic
        tags = resource_props.get("tags") or {}
        if isinstance(tags, dict) and tags.get("owner"):
            return ()
        return (
            {
                "rule_id": "dev.tighter-tags.owner-required",
                "denied": True,
                "reason": "missing_owner_tag",
            },
        )


def app() -> Starlette:
    """Factory. uvicorn invokes this once at server start with ``--factory``."""
    if os.environ.get(_DEV_ENV) != "1":
        raise RuntimeError(
            f"fdai.delivery.read_api._local requires {_DEV_ENV}=1; "
            "this module is a local dev entrypoint and MUST NOT boot in production."
        )
    read_model = InMemoryConsoleReadModel()
    _seed(read_model)
    resolver = RoleResolver(
        group_mapping=GroupMapping(
            reader_group_id="00000000-0000-0000-0000-000000000001",
            contributor_group_id="00000000-0000-0000-0000-000000000002",
            approver_group_id="00000000-0000-0000-0000-000000000003",
            owner_group_id="00000000-0000-0000-0000-000000000004",
            break_glass_group_id="00000000-0000-0000-0000-000000000005",
        )
    )
    authenticator = build_authenticator(
        verifier=UnsafeClaimsExtractor(),
        resolver=resolver,
    )

    # Load the shipped ontology + action-type catalogs so the console's
    # explorer / promotion-gate dashboards render out of the box.
    schema_registry = PackageResourceSchemaRegistry()
    object_types_root = _REPO_ROOT / "rule-catalog" / "vocabulary" / "object-types"
    link_types_root = _REPO_ROOT / "rule-catalog" / "vocabulary" / "link-types"
    action_types_root = _REPO_ROOT / "rule-catalog" / "action-types"

    ontology_object_types: tuple[Any, ...] = ()
    ontology_link_types: tuple[Any, ...] = ()
    action_types: tuple[Any, ...] = ()
    if object_types_root.is_dir():
        ontology_object_types = load_object_type_catalog(
            object_types_root, schema_registry=schema_registry
        )
        if link_types_root.is_dir():
            ontology_link_types = load_link_type_catalog(
                link_types_root,
                schema_registry=schema_registry,
                object_types=ontology_object_types,
            )
    if action_types_root.is_dir():
        action_types = load_action_type_catalog(
            action_types_root,
            schema_registry=schema_registry,
            probes_root=None,
        )

    # Load the shipped rule catalog so the console's Knowledge > Rules
    # panel renders every policy the system knows out of the box. Wrap
    # defensively: a catalog load failure MUST NOT take down the whole
    # dev server (the panel just stays unregistered / 404s).
    rule_catalog_rules: tuple[Any, ...] = ()
    catalog_root = _REPO_ROOT / "rule-catalog" / "catalog"
    policies_root = _REPO_ROOT / "policies"
    remediation_root = _REPO_ROOT / "rule-catalog" / "remediation"
    vocabulary_file = _REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"
    if catalog_root.is_dir() and action_types and vocabulary_file.is_file():
        try:
            with vocabulary_file.open("r", encoding="utf-8") as fh:
                resource_types = load_resource_type_registry_from_mapping(yaml.safe_load(fh))
            rule_catalog_rules = load_rule_catalog(
                catalog_root,
                schema_registry=schema_registry,
                action_types=action_types,
                resource_types=resource_types,
                policies_root=policies_root if policies_root.is_dir() else None,
                remediation_root=remediation_root if remediation_root.is_dir() else None,
            )
        except Exception:  # noqa: BLE001 - dev harness resilience only
            logging.getLogger(__name__).warning("rule_catalog_load_failed", exc_info=True)
            rule_catalog_rules = ()

    # Load the imported upstream corpus (Azure Policy built-ins,
    # kube-bench) - thousands of candidate / reference rules. These are
    # not all normalized to the canonical vocabulary, so they parse via
    # the pydantic model (schema only), NOT the strict catalog loader.
    rule_catalog_collected: tuple[Any, ...] = ()
    collected_root = _REPO_ROOT / "rule-catalog" / "collected"
    if collected_root.is_dir():
        collected: list[Any] = []
        for path in sorted(collected_root.rglob("*.yaml")):
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8"))
                if isinstance(raw, Mapping):
                    collected.append(Rule.model_validate(raw))
            except Exception:  # noqa: BLE001 - skip a malformed corpus file
                logging.getLogger(__name__).debug(
                    "collected_rule_skipped path=%s", path, exc_info=True
                )
        rule_catalog_collected = tuple(collected)

    trace_reader = ConsoleReadModelTraceReader(read_model)
    what_if_evaluators: dict[str, WhatIfEvaluator] = {
        "tighter-tags": _DemoTighterTagsEvaluator(),
    }

    # Real affected-resources for the console: evaluate the shipped Rego
    # policies against a small synthetic inventory. Wired only when the
    # active catalog + policies + OPA binary are all present; otherwise
    # the findings endpoint honestly reports "not evaluated here".
    rule_catalog_findings_provider: Any = None
    rule_catalog_findings_summary_provider: Any = None
    if rule_catalog_rules and policies_root.is_dir():
        try:
            from fdai.delivery.read_api.demo_findings import (
                build_demo_findings_provider,
                build_demo_findings_summary_provider,
            )

            _rules_by_id = {r.id: r for r in rule_catalog_rules}
            rule_catalog_findings_provider = build_demo_findings_provider(
                rules_by_id=_rules_by_id,
                policies_root=policies_root,
            )
            rule_catalog_findings_summary_provider = build_demo_findings_summary_provider(
                rules_by_id=_rules_by_id,
                policies_root=policies_root,
            )
        except MissingOpaBinaryError:
            logging.getLogger(__name__).info("demo_findings_disabled_no_opa")
            rule_catalog_findings_provider = None
            rule_catalog_findings_summary_provider = None

    return build_app(
        authenticator=authenticator,
        read_model=read_model,
        config=ReadApiConfig(
            dev_mode=True,
            cors_allow_origins=(
                "http://127.0.0.1:5173",
                "http://localhost:5173",
                "http://127.0.0.1:8090",
                "http://localhost:8090",
            ),
            live_stream=_build_live_stream_config(),
            blast_radius_graph=_build_blast_radius_graph(),
            ontology_object_types=tuple(ontology_object_types),
            ontology_link_types=tuple(ontology_link_types),
            rule_catalog_rules=tuple(rule_catalog_rules),
            rule_catalog_collected_rules=tuple(rule_catalog_collected),
            rule_catalog_policies_root=policies_root if policies_root.is_dir() else None,
            rule_catalog_remediation_root=(
                remediation_root if remediation_root.is_dir() else None
            ),
            rule_catalog_findings_provider=rule_catalog_findings_provider,
            rule_catalog_findings_summary_provider=rule_catalog_findings_summary_provider,
            promotion_gate_action_types=tuple(action_types),
            promotion_gate_source=InMemoryShadowVerdictSource(verdicts=_synthetic_verdicts()),
            trace_reader=trace_reader,
            bitemporal_reader=trace_reader,
            what_if_reader=trace_reader,
            what_if_evaluators=what_if_evaluators,
            chat=_build_chat_backend(),
            expose_pantheon=True,
        ),
    )


def _build_chat_backend() -> Any:
    """Resolve a CommandDeck chat backend from env vars.

    The dev harness ALWAYS wires a chat config (never ``None``) so the
    ``/chat`` route is always registered. When no upstream LLM is
    configured, ``backend_from_env`` returns a :class:`DisabledChatBackend`;
    the endpoint then responds with ``501`` and the FE falls back to
    its built-in deterministic answerer.

    Resolution order (see ``chat.backend_from_env`` for the full contract):

    1. ``FDAI_NARRATOR_BASE_URL`` + ``FDAI_NARRATOR_API_KEY`` +
       ``FDAI_NARRATOR_MODEL`` (API-key path - matches CLI narrator).
    2. ``resolved-models.json`` with a ``narrator`` block + a working
       ``az login`` (keyless Azure AD path - what a developer with the
       CLI narrator already gets for free).
    3. Otherwise disabled - the FE keeps working via the deterministic
       fallback.
    """

    from fdai.delivery.read_api.chat import backend_from_env

    return backend_from_env()


def _build_live_stream_config() -> LiveStreamConfig:
    """Compose the live-stream config for the dev harness.

    Preferred: attach a real :class:`ControlLoopLiveEmitter` so the
    console shows stage frames produced by the actual pipeline. If the
    shipped rule catalog cannot be composed (missing files, YAML errors)
    the emitter factory raises :class:`ControlLoopEmitterUnavailable`
    and we fall back to :class:`SyntheticLiveEmitter`, which emits the
    same wire format from a hardcoded distribution so the FE is never
    dark.

    The sink is created once here so it can be shared by the route
    consumer and (in a future round) any additional publisher we bolt
    on the same channel.
    """

    sink: SseSink = InMemorySseSink()
    channel = "aw.pipeline.stages"

    def _factory(sink_arg: SseSink, channel_arg: str) -> LiveEmitter:
        try:
            return build_control_loop_emitter(
                sink_arg,
                channel_arg,
                events_per_second=3.0,
            )
        except ControlLoopEmitterUnavailable:
            # Rule catalog not available; keep the console populated
            # with the hardcoded distribution. Match the rate we use
            # for the real emitter so the dev cockpit paces the same
            # whether or not the catalog compiled.
            return SyntheticLiveEmitter(sink=sink_arg, channel=channel_arg, events_per_second=3.0)

    return LiveStreamConfig(
        path="/live/stream",
        channel=channel,
        sink=sink,
        emitter_factory=_factory,
    )

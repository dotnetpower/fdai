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


def _seed(read_model: InMemoryConsoleReadModel) -> None:
    """Seed audit entries (with trust tiers) + one pending HIL so the SPA renders data."""
    # (tier, action_kind, outcome, recorded_at time) - a realistic T0-heavy split.
    entries: tuple[tuple[str, str, str, str], ...] = (
        ("t0", "control_loop.abstain", "abstained_t0", "10:00:00"),
        ("t0", "enable-encryption", "shadow_pr_opened", "10:05:00"),
        ("t0", "tag-compliance", "shadow_pr_opened", "10:12:00"),
        ("t0", "control_loop.abstain", "abstained_t0", "10:20:00"),
        ("t0", "right-size-disk", "shadow_pr_opened", "10:31:00"),
        ("t0", "close-idle-endpoint", "shadow_pr_opened", "10:38:00"),
        ("t1", "reuse-learned-action", "shadow_pr_opened", "10:42:00"),
        ("t1", "correlate-incident", "matched_prior", "10:48:00"),
        ("t2", "root-cause-reasoning", "escalated_hil", "10:55:00"),
    )
    for i, (tier, action_kind, outcome, hhmmss) in enumerate(entries, start=1):
        read_model.record_audit_entry(
            {
                "event_id": f"00000000-0000-0000-0000-{i:012d}",
                "actor": "fdai.core.control_loop",
                "action_kind": action_kind,
                "mode": "shadow",
                "outcome": outcome,
                "tier": tier,
                "recorded_at": f"2026-07-06T{hhmmss}+00:00",
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
    if rule_catalog_rules and policies_root.is_dir():
        try:
            from fdai.delivery.read_api.demo_findings import build_demo_findings_provider

            rule_catalog_findings_provider = build_demo_findings_provider(
                rules_by_id={r.id: r for r in rule_catalog_rules},
                policies_root=policies_root,
            )
        except MissingOpaBinaryError:
            logging.getLogger(__name__).info("demo_findings_disabled_no_opa")
            rule_catalog_findings_provider = None

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

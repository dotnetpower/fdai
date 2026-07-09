"""Dev-only :class:`LiveEmitter` that pumps synthetic events through a
real :class:`~fdai.core.control_loop.ControlLoop`.

Where :class:`~fdai.delivery.read_api.live_stream.SyntheticLiveEmitter`
publishes hand-crafted ``StageEvent`` frames straight into an
:class:`~fdai.shared.providers.sse.SseSink`, this emitter runs an
actual :class:`ControlLoop` in-process with the shipped rule catalog,
attached to a :class:`SseSinkStagePublisher` on the same sink. Every
frame the local console renders is produced by the pipeline that would
run in production - the trust router, T0 engine, action builder, and
shadow executor really evaluate the event.

This is **dev only**. Production wires a Kafka-backed
:class:`~fdai.core.control_loop.ControlLoop` (see ``__main__.py``); the
read-API pod there does NOT run the pipeline, it subscribes to the
``aw.pipeline.stages`` Kafka topic via
:class:`~fdai.shared.streaming.broadcaster.SseBroadcaster` and fans out
to browsers. Both paths land on the same wire (SSE ``event: stage``
frames), so the FE code does not change between them.

Failure modes
-------------

- **Missing OPA binary** - T0 evaluates every candidate to "abstain"
  (same fallback as :mod:`fdai.__main__`), and only ingest / route /
  audit stages fire. The FE still receives a live cockpit, just without
  gate / execute frames.
- **Rule catalog load error** - :meth:`start` raises
  :class:`ControlLoopEmitterUnavailable`; the app factory catches and
  falls back to :class:`SyntheticLiveEmitter` so the console is still
  populated.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from fdai.core.control_loop import ControlLoop
from fdai.core.event_ingest import EventIngest
from fdai.core.executor import (
    ResourceLockManager,
    ShadowExecutor,
    TemplateRenderer,
)
from fdai.core.executor.action_builder import ActionBuilder
from fdai.core.tiers.t0_deterministic import (
    MissingOpaBinaryError,
    OpaRegoEvaluator,
    RuleIndex,
    T0Engine,
)
from fdai.core.trust_router import TrustRouter
from fdai.delivery.read_api.live_stream import LiveEmitter
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.resource_type import (
    load_resource_type_registry_from_mapping,
)
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import (
    JsonSchemaContractValidator,
    JsonSchemaEventValidator,
)
from fdai.shared.providers.sse import SseSink
from fdai.shared.providers.stage_publisher import (
    StageEvent,
    StageName,
    StagePublisher,
)
from fdai.shared.providers.testing import (
    InMemoryStateStore,
    RecordingRemediationPrPublisher,
)
from fdai.shared.streaming.stage_publisher import SseSinkStagePublisher

_LOGGER = logging.getLogger(__name__)


# Stage -> owning pantheon agent. The dev ControlLoop is single-process, so
# we attribute each SSE frame to the agent that owns that stage at the
# stream boundary (the real multi-agent pipeline stamps producer_principal
# itself). Gate frames split by decision: a HIL verdict is Var's approval,
# everything else is Forseti's judgment.
_STAGE_AGENT: dict[StageName, str] = {
    StageName.INGEST: "Huginn",
    StageName.ROUTE: "Heimdall",
    StageName.VERIFY: "Forseti",
    StageName.GATE: "Forseti",
    StageName.EXECUTE: "Thor",
    StageName.AUDIT: "Saga",
}


def _stage_agent(stage: StageName, detail: dict[str, Any]) -> str:
    if stage is StageName.GATE and str(detail.get("gate_decision")) == "hil":
        return "Var"
    return _STAGE_AGENT.get(stage, "unknown")


class _AgentAttributingStagePublisher:
    """Wrap a StagePublisher to stamp the owning agent (producer_principal)
    onto each frame's detail, so the Live cockpit can show which agent did
    each step. Dev-only: production's real pipeline stamps this itself."""

    def __init__(self, inner: StagePublisher) -> None:
        self._inner = inner

    async def emit(self, event: StageEvent) -> None:
        detail = dict(event.detail or {})
        detail.setdefault("producer_principal", _stage_agent(event.stage, detail))
        await self._inner.emit(replace(event, detail=detail))


class ControlLoopEmitterUnavailableError(RuntimeError):
    """Raised when the dev ControlLoop cannot be composed.

    The caller (``_local.py``) SHOULD catch this and fall back to a
    simpler emitter so the console still renders something.
    """


# Backward-compat alias for the shorter name used in earlier drafts / docs.
ControlLoopEmitterUnavailable = ControlLoopEmitterUnavailableError


@dataclass
class ControlLoopLiveEmitter(LiveEmitter):
    """Pump synthetic events through a real ControlLoop.

    The emitter's task is one loop that:

    1. Picks the next event from :attr:`event_source` (cycling).
    2. Rewrites its ``idempotency_key`` so ``event_ingest`` does not
       deduplicate the cycle.
    3. Calls :meth:`ControlLoop.process(event)`. The loop's injected
       :class:`SseSinkStagePublisher` publishes stage frames onto the
       sink; the SSE route wakes up and streams them to browsers.
    4. Sleeps to keep the rate near :attr:`events_per_second`.
    """

    sink: SseSink
    channel: str = "aw.pipeline.stages"
    events_per_second: float = 10.0
    repo_root: Path | None = None
    """Repository root. When ``None`` we infer from ``fdai.__file__``."""

    _task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _running: bool = field(default=False, init=False, repr=False)
    _loop: ControlLoop | None = field(default=None, init=False, repr=False)
    _events: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)
    _counter: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.events_per_second <= 0:
            raise ValueError("events_per_second MUST be positive")
        if not self.channel:
            raise ValueError("channel MUST be non-empty")

    async def start(self) -> None:
        if self._running:
            return
        self._loop = self._build_control_loop()
        self._events = self._load_events()
        if not self._events:
            raise ControlLoopEmitterUnavailable(
                "no scenario events found for the dev pump - "
                "check tests/scenarios/v2026.07/ ships with the repo"
            )
        self._running = True
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._run(), name="fdai.live.control-loop-emitter")

    async def stop(self) -> None:
        self._running = False
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001
                _LOGGER.debug("live_control_loop_emitter_stop_exception", exc_info=True)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _resolve_repo_root(self) -> Path:
        if self.repo_root is not None:
            return self.repo_root
        # ``src/fdai/delivery/read_api/live_control_loop.py`` -> repo root
        return Path(__file__).resolve().parents[4]

    def _build_control_loop(self) -> ControlLoop:
        repo_root = self._resolve_repo_root()
        catalog_root = repo_root / "rule-catalog" / "catalog"
        action_types_root = repo_root / "rule-catalog" / "action-types"
        policies_root = repo_root / "policies"
        remediation_root = repo_root / "rule-catalog" / "remediation"
        vocabulary_file = repo_root / "rule-catalog" / "vocabulary" / "resource-types.yaml"
        for path in (
            catalog_root,
            action_types_root,
            policies_root,
            remediation_root,
            vocabulary_file,
        ):
            if not path.exists():
                raise ControlLoopEmitterUnavailable(f"missing catalog path: {path}")

        try:
            registry = PackageResourceSchemaRegistry()
            action_types = load_action_type_catalog(action_types_root, schema_registry=registry)
            with vocabulary_file.open("r", encoding="utf-8") as fh:
                resource_types = load_resource_type_registry_from_mapping(yaml.safe_load(fh))
            rules = load_rule_catalog(
                catalog_root,
                schema_registry=registry,
                action_types=action_types,
                resource_types=resource_types,
                policies_root=policies_root,
                remediation_root=remediation_root,
            )
        except Exception as exc:  # noqa: BLE001 - propagate as unavailable
            raise ControlLoopEmitterUnavailable(f"rule catalog load failed: {exc}") from exc

        try:
            evaluator: Any = OpaRegoEvaluator(policies_root=policies_root)
        except MissingOpaBinaryError:
            _LOGGER.warning("live_control_loop_emitter_no_opa_fallback_to_abstain")
            evaluator = None

        index = RuleIndex.build(rules)
        # Bounded stores: the live pump is a firehose (3+ eps × hours)
        # whose *output* (SSE frames via the stage publisher below) is
        # what the UI reads. The audit chain + PR history here are only
        # needed to satisfy the control-loop contract; nobody reads
        # them back. Cap both so a multi-hour dev session does not
        # grow unbounded (~2.2 MB / minute otherwise).
        audit_store = InMemoryStateStore(max_audit_entries=2000)
        executor = ShadowExecutor(
            publisher=RecordingRemediationPrPublisher(max_records=2000),
            audit_store=audit_store,
            renderer=TemplateRenderer(remediation_root=remediation_root),
            resource_lock=ResourceLockManager(),
        )
        action_types_by_name = {a.name: a for a in action_types}
        validator = JsonSchemaEventValidator(
            JsonSchemaContractValidator(PackageResourceSchemaRegistry())
        )
        stage_publisher = _AgentAttributingStagePublisher(
            SseSinkStagePublisher(self.sink, channel=self.channel)
        )

        # NOTE on risk-gate wiring.
        # The shipped risk table + shipped ActionTypes route the vast
        # majority of the synthetic templates below to HIL (production
        # tag / data-plane touched / cost >= $100 / etc.). Wiring it in
        # the dev pump produces a 100%-HIL screen that contradicts the
        # roadmap's "deterministic-first, ~5-10% HIL" target and burns
        # the visual signal that HIL is meant to carry. We keep the
        # risk gate OFF here so the console shows what a healthy
        # autonomous pipeline looks like (mostly auto, a handful of
        # abstains). A fork that wants the full production posture
        # binds its own composition root.
        return ControlLoop(
            event_ingest=EventIngest(validator=validator),
            trust_router=TrustRouter(index=index),
            t0_engine=T0Engine(index=index, evaluator=evaluator),
            action_builder=ActionBuilder(action_types_by_name=action_types_by_name),
            executor=executor,
            audit_store=audit_store,
            rules_by_id={r.id: r for r in rules},
            action_types_by_name=action_types_by_name,
            stage_publisher=stage_publisher,
        )

    def _load_events(self) -> list[dict[str, Any]]:
        """Compose the dev event source.

        Two layers are merged so the FE sees breadth AND realism:

        1. **Shipped scenario events** under ``tests/scenarios/v2026.07/`` -
           the same fixtures the regression suite replays. They are the
           "known good" payloads that exercise specific rules end-to-end.
        2. **Synthetic broad-coverage templates** - one event per
           resource type in the shipped catalog, tuned to make (some) T0
           rules match. These push the swarm through many verticals /
           tiers / gate decisions rather than repeating the same 9
           scenarios.

        The pump cycles the merged list at :attr:`events_per_second`; each
        cycle rewrites identity fields (event_id / correlation_id /
        idempotency_key) so every emit is a fresh tile.
        """
        repo_root = self._resolve_repo_root()
        scenario_dir = repo_root / "tests" / "scenarios" / "v2026.07"
        enrichment_dir = repo_root / "tests" / "scenarios" / "enrichment" / "v2026.07"
        events: list[dict[str, Any]] = []
        for path in sorted(scenario_dir.glob("*.json")):
            try:
                scenario = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            event = scenario.get("event")
            if not isinstance(event, dict):
                continue
            merged = dict(event)
            enrichment_path = enrichment_dir / path.name
            if enrichment_path.exists():
                try:
                    overlay = json.loads(enrichment_path.read_text(encoding="utf-8"))
                    resource = overlay.get("event_payload_resource")
                    if isinstance(resource, dict):
                        payload = dict(merged.get("payload") or {})
                        payload["resource"] = resource
                        merged["payload"] = payload
                except (OSError, ValueError):
                    pass
            events.append(merged)

        events.extend(_synthetic_broad_coverage_templates())
        return events

    async def _run(self) -> None:
        if self._loop is None:  # defensive; start() populates this before create_task
            return
        loop = self._loop
        interval = 1.0 / self.events_per_second
        try:
            while self._running:
                base = self._events[self._counter % len(self._events)]
                self._counter += 1
                event = _clone_event_with_fresh_ids(base, self._counter)
                try:
                    await loop.process(event)
                except Exception:  # noqa: BLE001 - dev pump keeps going
                    _LOGGER.debug("live_control_loop_process_error", exc_info=True)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass


def _clone_event_with_fresh_ids(base: dict[str, Any], counter: int) -> dict[str, Any]:
    """Deep-copy ``base`` and substitute unique identity fields.

    Ensures every emit has:
      - a fresh ``event_id`` / ``correlation_id`` UUID so the FE renders
        a new tile (see :meth:`ControlLoopLiveEmitter._run`),
      - an idempotency key that will not collide with a previous cycle
        (avoids :class:`EventIngest` dedup),
      - a resource id that substitutes any ``{{idx}}`` placeholder with
        the counter, so autonomy appears to act on many targets rather
        than the same one repeatedly.
    """
    event_uuid = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    event = {**base}
    event["event_id"] = event_uuid
    event["correlation_id"] = event_uuid
    event["idempotency_key"] = f"live-{counter:012d}"
    event["ingested_at"] = now
    payload = dict(event.get("payload") or {})
    resource = payload.get("resource")
    if isinstance(resource, dict):
        resource = dict(resource)
        rid = resource.get("resource_id")
        if isinstance(rid, str) and "{{idx}}" in rid:
            resource["resource_id"] = rid.replace("{{idx}}", str(counter))
        payload["resource"] = resource
    event["payload"] = payload
    return event


def build_control_loop_emitter(
    sink: SseSink,
    channel: str,
    *,
    events_per_second: float = 10.0,
    repo_root: Path | None = None,
) -> ControlLoopLiveEmitter:
    """Factory suitable for ``LiveStreamConfig.emitter_factory``.

    ``build_app`` invokes the ``emitter_factory`` with ``(sink,
    channel)`` and expects a :class:`LiveEmitter`. This helper adds the
    other ControlLoop-specific parameters using defaults.
    """
    return ControlLoopLiveEmitter(
        sink=sink,
        channel=channel,
        events_per_second=events_per_second,
        repo_root=repo_root,
    )


def _synthetic_broad_coverage_templates() -> list[dict[str, Any]]:
    """Return one event per shipped resource type.

    These templates route through the full pipeline (route -> verify ->
    gate -> execute or abstain), so the FE swarm sees diverse tier /
    rule / vertical / gate-decision combinations rather than the same
    handful cycled forever.

    The ``resource_id`` is templated with ``{{idx}}`` so the pump can
    substitute a fresh, unique id per cycle - otherwise a single rule
    would keep firing on the same target and the FE would think
    autonomy is chasing one resource.

    Props are tuned to sometimes match, sometimes not, so gate
    decisions vary organically (auto / hil / abstain / deny).
    """
    now_iso = datetime.now(UTC).isoformat()

    def base(event_type: str) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "event_id": "00000000-0000-0000-0000-000000000000",
            "idempotency_key": "will-be-overwritten",
            "source": "live_synthetic",
            "event_type": event_type,
            "detected_at": now_iso,
            "ingested_at": now_iso,
            "mode": "shadow",
        }

    templates: list[dict[str, Any]] = [
        {
            **base("cost_recommendation"),
            "payload": {
                "resource": {
                    "resource_id": "vm-idle-{{idx}}",
                    "type": "compute.vm",
                    "props": {
                        "cpu_p95_percent": 3,
                        "network_p95_bytes": 512,
                        "memory_p95_percent": 8,
                        "tags": {"environment": "prod"},
                    },
                },
            },
        },
        {
            **base("cost_recommendation"),
            "payload": {
                "resource": {
                    "resource_id": "vm-oversized-{{idx}}",
                    "type": "compute.vm",
                    "props": {
                        "cpu_p95_percent": 12,
                        "memory_p95_percent": 18,
                        "tags": {"environment": "prod"},
                    },
                },
            },
        },
        {
            **base("change_detected"),
            "payload": {
                "resource": {
                    "resource_id": "vmss-{{idx}}",
                    "type": "compute.vm-scale-set",
                    "props": {
                        "capacity": 40,
                        "utilization_p95_percent": 12,
                        "zones": ["1"],
                    },
                },
            },
        },
        {
            **base("orphan_detected"),
            "payload": {
                "resource": {
                    "resource_id": "disk-orphan-{{idx}}",
                    "type": "disk",
                    "props": {
                        "attached": False,
                        "size_gib": 128,
                        "age_days": 45,
                        "snapshot_policy_present": False,
                    },
                },
            },
        },
        {
            **base("change_detected"),
            "payload": {
                "resource": {
                    "resource_id": "aks-{{idx}}",
                    "type": "kubernetes-cluster",
                    "props": {
                        "rbac_enabled": True,
                        "network_policy": None,
                        "private_cluster": False,
                        "diagnostic_settings_present": False,
                    },
                },
            },
        },
        {
            **base("change_detected"),
            "payload": {
                "resource": {
                    "resource_id": "aks-nodepool-{{idx}}",
                    "type": "kubernetes-node-pool",
                    "props": {
                        "zones": ["1"],
                        "node_count": 24,
                        "utilization_p95_percent": 15,
                    },
                },
            },
        },
        {
            **base("change_detected"),
            "payload": {
                "resource": {
                    "resource_id": "log-workspace-{{idx}}",
                    "type": "log-workspace",
                    "props": {"retention_days": 730},
                },
            },
        },
        {
            **base("change_detected"),
            "payload": {
                "resource": {
                    "resource_id": "lb-{{idx}}",
                    "type": "network.load-balancer",
                    "props": {"backend_pool_targets": 0},
                },
            },
        },
        {
            **base("change_detected"),
            "payload": {
                "resource": {
                    "resource_id": "nsg-{{idx}}",
                    "type": "network.nsg",
                    "props": {
                        "security_rules": [
                            {
                                "direction": "Inbound",
                                "access": "Allow",
                                "protocol": "*",
                                "source_address_prefix": "*",
                                "destination_port_range": "22",
                            },
                        ],
                    },
                },
            },
        },
        {
            **base("change_detected"),
            "payload": {
                "resource": {
                    "resource_id": "pip-orphan-{{idx}}",
                    "type": "network.public-ip",
                    "props": {"attached": False},
                },
            },
        },
        {
            **base("change_detected"),
            "payload": {
                "resource": {
                    "resource_id": "storage-{{idx}}",
                    "type": "object-storage",
                    "props": {
                        "public_access_enabled": True,
                        "tls_minimum_version": "TLS1_0",
                    },
                },
            },
        },
        {
            **base("change_detected"),
            "payload": {
                "resource": {
                    "resource_id": "sql-db-{{idx}}",
                    "type": "sql-database",
                    "props": {"backup_geo_redundant": False, "tde_enabled": False},
                },
            },
        },
        {
            **base("change_detected"),
            "payload": {
                "resource": {
                    "resource_id": "pg-server-{{idx}}",
                    "type": "postgresql-server",
                    "props": {"public_network_access_enabled": True, "ssl_enforcement": "Disabled"},
                },
            },
        },
        {
            **base("change_detected"),
            "payload": {
                "resource": {
                    "resource_id": "kv-{{idx}}",
                    "type": "secret-store",
                    "props": {"purge_protection_enabled": False, "soft_delete_days": 7},
                },
            },
        },
        {
            **base("change_detected"),
            "payload": {
                "resource": {
                    "resource_id": "cache-{{idx}}",
                    "type": "cache",
                    "props": {"tier": "Premium", "zones": ["1"]},
                },
            },
        },
        {
            **base("change_detected"),
            "payload": {
                "resource": {
                    "resource_id": "rg-{{idx}}",
                    "type": "resource-group",
                    "props": {"tags": {"cost-center": None}},
                },
            },
        },
    ]
    return templates


__all__ = [
    "ControlLoopEmitterUnavailable",
    "ControlLoopEmitterUnavailableError",
    "ControlLoopLiveEmitter",
    "build_control_loop_emitter",
]

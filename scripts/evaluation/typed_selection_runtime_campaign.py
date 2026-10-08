#!/usr/bin/env python3
"""Bounded runtime shadow campaign for typed instance selection (#2011).

Runs the exact runtime path: ``build_ontology_index_runtime`` with the composed shadow binding,
Muninn/Heimdall/Saga index preparation, the Bragi-scoped ``query`` entry point, and the detached
observer. A paired runtime without a shadow binding measures the unchanged answer path. Each
planned decision issues one shadow-off call, one shadow-on call that schedules one K=2
observation, and one contended probe while that observation is in flight.

The campaign judges pre-registered protocols ``typed-selection-runtime-latency.v1`` and
``typed-selection-runtime-window.v1`` over ``instance-runtime-window.v1.json`` with R=4. Live
mode needs explicit authorization. It makes at most 512 proposal calls within a 90-minute total
deadline, never retries, and stops after three consecutive provider-unavailable observations or
once the unavailable allowance is exhausted. ``--fake`` answers from labels through the real
adapter request path without authentication or network.

Evidence stays private: decision rows and terminal shadow rows are written mode 0600 to
``--evidence-dir``; stdout prints aggregate figures only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

if __package__ is None or __package__ == "":
    _REPO_ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(_REPO_ROOT))
    sys.path.insert(0, str(_REPO_ROOT / "services/core-control-plane/src"))
    sys.path.insert(0, str(_REPO_ROOT / "packages/service-contracts/src"))

import httpx
import yaml
from fdai.agents import PantheonRuntime, StateStoreAuditChainAdapter
from fdai.agents.saga import Saga
from fdai.composition.semantic_query_instance_candidates import declare_instance_candidate_query
from fdai.composition.typed_selection_shadow import (
    SHADOW_CONFIG_RELATIVE_PATH,
    TypedSelectionShadowPin,
    bind_qualified_proposer,
    capability_matches_pin,
)
from fdai.core.conversation.semantic_manifest import semantic_principal_scope_digest
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.operational_functions import operational_function_types
from fdai.delivery.catalog_search.ontology_typed_selection_campaign import (
    WINDOW_CASE_SET,
    ForegroundPair,
    ObservationLatency,
    WindowDecision,
    evaluate_latency,
    evaluate_window,
)
from fdai.delivery.catalog_search.ontology_typed_selection_shadow import (
    SHADOW_TERMINAL_PREFIX,
    TypedSelectionShadowBinding,
    TypedSelectionShadowBudget,
)
from fdai.rule_catalog.schema.object_type import load_object_type_from_mapping
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog
from fdai.rule_catalog.schema.property_semantic import empty_property_semantic_registry
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.runtime.ontology_index_runtime import OntologyIndexRuntime, build_ontology_index_runtime
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.ontology_query import content_digest

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "eval/ontology-retrieval"
REPEATS = 4
TOTAL_DEADLINE_SECONDS = 90 * 60
MAX_CONSECUTIVE_UNAVAILABLE = 3
MAX_UNAVAILABLE = 5
_PROVIDER_UNAVAILABLE = frozenset({"proposal_unavailable", "deadline_exceeded"})


class CampaignAbortedError(RuntimeError):
    """The bounded campaign stopped before every planned decision completed."""


@dataclass(frozen=True, slots=True)
class Case:
    case_id: str
    query: str
    language: str
    expected: frozenset[str]


class _LocalEmbedder:
    """Deterministic local vectors; typed selection never ranks by embedding."""

    embedding_space_id = "typed-selection-runtime-campaign"
    embedding_model_version = "local-deterministic-v1"
    dim = 8

    async def embed(self, text: str) -> tuple[float, ...]:
        digest = content_digest({"text": text})
        return tuple(
            (int(digest[7 + index * 2 : 9 + index * 2], 16) / 255.0) - 0.5 for index in range(8)
        )


def _load(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((ASSETS / name).read_text(encoding="utf-8"))
    return loaded


def load_cases() -> tuple[Case, ...]:
    return tuple(
        Case(
            case_id=item["case_id"],
            query=item["query"],
            language=item["cohort"].split("-", 1)[0],
            expected=frozenset(item["expected_document_ids"]),
        )
        for item in _load(WINDOW_CASE_SET)["cases"]
    )


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


async def _build_runtimes(
    binding: TypedSelectionShadowBinding,
) -> tuple[tuple[OntologyIndexRuntime, InMemoryStateStore], ...]:
    corpus = _load("instance-corpus.v1.json")
    registry = PackageResourceSchemaRegistry()
    declarations = tuple(
        load_object_type_from_mapping(
            yaml.safe_load(
                (ROOT / f"rule-catalog/vocabulary/object-types/{name}.yaml").read_text()
            ),
            schema_registry=registry,
        )
        for name in corpus["required_object_types"]
    )
    resource_types = load_resource_type_registry_from_mapping(
        yaml.safe_load((ROOT / "rule-catalog/vocabulary/resource-types.yaml").read_text())
    )
    catalog = declare_instance_candidate_query(
        OntologyCatalog(
            object_types=declarations,
            link_types=(),
            interface_types=(),
            interface_implementations=(),
            action_types=(),
            property_semantics=empty_property_semantic_registry(),
            resource_types=resource_types,
        )
    )
    release = build_ontology_release(
        object_types=catalog.object_types,
        function_types=operational_function_types(catalog.function_types),
    )
    runtimes: list[tuple[OntologyIndexRuntime, InMemoryStateStore]] = []
    for shadow in (None, binding):
        state = InMemoryStateStore()
        ontology = InMemoryOntologyInstanceStore(
            object_types=declarations, link_types=(), source_generation="runtime-window-v1"
        )
        for item in corpus["objects"]:
            await ontology.upsert_object(OntologyObjectRecord(**item))
        runtime = build_ontology_index_runtime(
            store=state,
            ontology_store=ontology,
            catalog=catalog,
            release=release,
            embedder=_LocalEmbedder(),
            clock=lambda: datetime.now(UTC),
            typed_selection_shadow=shadow,
        )
        if runtime is None or runtime.workers is None:
            raise CampaignAbortedError("runtime factory did not bind the instance index")
        runtimes.append((runtime, state))
    return tuple(runtimes)


def _context(request_ref: str) -> FunctionInvocationContext:
    principal = Principal(id="campaign-reader", role=Role.READER, groups=frozenset())
    return FunctionInvocationContext(
        caller_agent="Bragi",
        principal_ref=principal.id,
        principal_scope_digest=semantic_principal_scope_digest(
            principal=principal, purpose="operations-review"
        ),
        purposes=("operations-review",),
        authentication_request_ref=request_ref,
    )


async def _prepare(runtime: OntologyIndexRuntime, store: InMemoryStateStore) -> None:
    if runtime.workers is None:
        raise CampaignAbortedError("runtime instance index workers are unavailable")
    pantheon = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="raw-events",
        saga=Saga(audit_chain=StateStoreAuditChainAdapter(store)),
        context_index_workers=runtime.workers.bindings,
    )
    probe = "object:Resource:example-resource-a"
    for _attempt in range(3):
        try:
            result = await runtime.query(probe, 5, _context("campaign-prepare"))
        except ValueError:
            await runtime.reconcile(pantheon)
            for _ in range(8):
                await pantheon.run()
            continue
        if result["candidates"]:
            return
    raise CampaignAbortedError("runtime index did not reach a sealed active generation")


async def _call(runtime: OntologyIndexRuntime, query: str, request_ref: str) -> tuple[float, str]:
    started = time.perf_counter()
    try:
        result = await runtime.query(query, 20, _context(request_ref))
        outcome = "returned:" + str(result["result_digest"])
    except Exception as exc:  # noqa: BLE001 - the outcome identity is what is compared
        outcome = f"error:{type(exc).__name__}:{exc}"
    return (time.perf_counter() - started) * 1000, outcome


async def _loop_lag(samples: list[float], stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    while not stop.is_set():
        expected = loop.time() + 0.01
        await asyncio.sleep(0.01)
        samples.append(max(0.0, (loop.time() - expected) * 1000))


async def run_campaign(
    *,
    binding: TypedSelectionShadowBinding,
    cases: Sequence[Case],
    repeats: int,
    probe_delay_seconds: float,
    progress: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Run every planned decision and return private rows plus both protocol reports."""
    (off, off_store), (on, store) = await _build_runtimes(binding)
    await _prepare(off, off_store)
    await _prepare(on, store)
    if on.workers is None:
        raise CampaignAbortedError("runtime instance index workers are unavailable")
    observer = on.workers._typed_selection_shadow
    if observer is None:
        raise CampaignAbortedError("shadow observer was not bound")
    lag: list[float] = []
    stop = asyncio.Event()
    monitor = asyncio.create_task(_loop_lag(lag, stop))
    rows: list[dict[str, Any]] = []
    consecutive = unavailable = 0
    deadline = time.monotonic() + TOTAL_DEADLINE_SECONDS
    try:
        for repeat in range(1, repeats + 1):
            for case in cases:
                if time.monotonic() >= deadline:
                    raise CampaignAbortedError("campaign total deadline exceeded")
                ref = f"campaign:{case.case_id}:r{repeat}"
                await observer.wait_idle()
                off_ms, off_outcome = await _call(off, case.query, ref + ":off")
                _on_ms, on_outcome = await _call(on, case.query, ref)
                await asyncio.sleep(probe_delay_seconds)
                contended_ms, contended_outcome = await _call(on, case.query, ref + ":probe")
                await observer.wait_idle()
                terminal = next(
                    (
                        dict(value)
                        for value in await store.read_states(SHADOW_TERMINAL_PREFIX, limit=64)
                        if value.get("request_ref") == ref
                    ),
                    None,
                )
                if terminal is None:
                    raise CampaignAbortedError("shadow observation left no terminal row")
                reason = terminal["unavailable_reason"]
                provider_failure = reason in _PROVIDER_UNAVAILABLE
                consecutive = consecutive + 1 if provider_failure else 0
                unavailable += reason is not None
                rows.append(
                    {
                        "case_id": case.case_id,
                        "repeat": repeat,
                        "language": case.language,
                        "expected": sorted(case.expected),
                        "gated_outcome": terminal["gated_outcome"],
                        "gated_document_ids": terminal["gated_document_ids"],
                        "unavailable_reason": reason,
                        "latency_ms": terminal["latency_ms"],
                        "off_ms": off_ms,
                        "contended_ms": contended_ms,
                        "same_outcome": off_outcome == on_outcome == contended_outcome,
                        "terminal": terminal,
                    }
                )
                if consecutive >= MAX_CONSECUTIVE_UNAVAILABLE or unavailable > MAX_UNAVAILABLE:
                    raise CampaignAbortedError("provider unavailability exceeded the allowance")
            progress(f"repeat {repeat}/{repeats} complete: {len(rows)} decisions")
    finally:
        stop.set()
        await monitor
        await on.workers.aclose_shadow()
    return {"rows": rows, "event_loop_lag_ms": lag}


def judge(rows: Sequence[Mapping[str, Any]], lag: Sequence[float]) -> dict[str, Any]:
    latency = evaluate_latency(
        observations=[
            ObservationLatency(float(row["latency_ms"]), row["unavailable_reason"]) for row in rows
        ],
        foreground=[
            ForegroundPair(
                float(row["off_ms"]), float(row["contended_ms"]), bool(row["same_outcome"])
            )
            for row in rows
        ],
        event_loop_lag_ms=list(lag) or [0.0],
    )
    window = evaluate_window(
        [
            WindowDecision(
                row["case_id"],
                row["language"],
                frozenset(row["expected"]),
                row["gated_outcome"],
                frozenset(row["gated_document_ids"]),
            )
            for row in rows
        ]
    )
    return {
        "latency": asdict(latency) | {"passed": latency.passed},
        "window": {
            **{key: value for key, value in asdict(window).items() if key != "languages"},
            "passed": window.passed,
            "languages": [
                asdict(item) | {"correct_rate": round(item.correct_rate, 4)}
                for item in window.languages
            ],
        },
    }


def _fake_binding(cases: Sequence[Case]) -> tuple[TypedSelectionShadowBinding, httpx.AsyncClient]:
    by_query = {case.query: case for case in cases}

    async def answer(request: httpx.Request) -> httpx.Response:
        query = json.loads(json.loads(request.content)["messages"][1]["content"])[
            "untrusted_input"
        ]["query"]
        ids: dict[str, list[str]] = defaultdict(list)
        for document_id in sorted(by_query[query].expected):
            _, object_type, identifier = document_id.split(":", 2)
            ids[object_type].append(identifier)
        clauses = [
            {"object_type": name, "predicates": [], "object_ids": values, "quote": query}
            for name, values in sorted(ids.items())
        ]
        proposal = {
            "status": "select" if clauses else "clarify",
            "reason": "conditions_proposed" if clauses else "ambiguous_request",
            "clauses": clauses,
        }
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(proposal)}}]
            },
        )

    class _FakeIdentity:
        async def get_token(self, audience: str) -> Any:
            from fdai.shared.providers.workload_identity import IdentityToken

            return IdentityToken(
                token="fake-token",  # noqa: S106 - offline fake transport only
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
                audience=audience,
            )

    from fdai.delivery.azure.llm.request_target import ModelRequestTarget

    pin = TypedSelectionShadowPin.load(ROOT / SHADOW_CONFIG_RELATIVE_PATH)
    http = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    composed = bind_qualified_proposer(
        pin,
        target=ModelRequestTarget(
            endpoint="https://example.invalid",
            deployment="fake-deployment",
            api_version="2024-10-21",
            model_family=pin.model_family,
        ),
        identity=_FakeIdentity(),
        http_client=http,
        catalog_root=ROOT / "rule-catalog",
        owner_loop=asyncio.get_running_loop(),
    )
    if composed.binding is None:
        raise CampaignAbortedError(composed.reason)
    return _campaign_budget(composed.binding), http


def _campaign_budget(binding: TypedSelectionShadowBinding) -> TypedSelectionShadowBinding:
    return TypedSelectionShadowBinding(
        proposer=binding.proposer,
        data_handling_policy_digest=binding.data_handling_policy_digest,
        expected_binding=binding.expected_binding,
        budget=TypedSelectionShadowBudget(
            max_observations_per_hour=600, max_principal_observations_per_hour=600
        ),
    )


def _live_binding(
    runtime_env: Path,
) -> tuple[TypedSelectionShadowBinding, httpx.AsyncClient, dict[str, str]]:
    from fdai.composition.resolved_models import _capability, _load_resolved_models
    from fdai.composition.semantic_query_model_targets import t2_model_targets
    from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
    from fdai.runtime.configuration import _model_endpoint_resolver

    values: dict[str, str] = {}
    for line in runtime_env.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    pin = TypedSelectionShadowPin.load(ROOT / SHADOW_CONFIG_RELATIVE_PATH)
    resolved = _load_resolved_models(values["LLM_RESOLVED_MODELS_PATH"])
    capability = _capability(resolved, pin.model_capability)
    if capability is None or not capability_matches_pin(pin, capability):
        raise CampaignAbortedError("resolved model is not the qualified family and version")
    endpoint = values.get("FDAI_LLM_ENDPOINT") or None
    targets = t2_model_targets(
        resolved,
        endpoint=endpoint,
        endpoint_resolver=(
            _model_endpoint_resolver(endpoint, values.get("FDAI_MODEL_ENDPOINTS_JSON"))
            if endpoint is not None
            else None
        ),
    )
    if not targets:
        raise CampaignAbortedError("no qualified model target is resolvable")
    http = httpx.AsyncClient(timeout=30)
    composed = bind_qualified_proposer(
        pin,
        target=targets[0],
        identity=AsyncAzureCliWorkloadIdentity.from_env(),
        http_client=http,
        catalog_root=ROOT / "rule-catalog",
        owner_loop=asyncio.get_running_loop(),
    )
    if composed.binding is None:
        raise CampaignAbortedError(composed.reason)
    attestation = {
        "model_family": str(capability.family),
        "model_version": str(capability.version),
        "deployment_digest": composed.binding.expected_binding.deployment_digest,
    }
    return _campaign_budget(composed.binding), http, attestation


def _write_private(path: Path, text: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--runtime-env", type=Path)
    parser.add_argument("--fake", action="store_true")
    args = parser.parse_args()
    if not args.fake and args.runtime_env is None:
        parser.error("live mode requires --runtime-env")
    if _git("status", "--porcelain", "--untracked-files=no"):
        raise SystemExit("tracked worktree must be clean")
    source_commit = _git("rev-parse", "HEAD")
    cases = load_cases()
    attestation: dict[str, str] = {"mode": "fake"}
    if args.fake:
        binding, http = _fake_binding(cases)
    else:
        binding, http, attestation = _live_binding(args.runtime_env)
    args.evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    started = datetime.now(UTC).isoformat()
    status = "completed"
    try:
        async with http:
            result = await run_campaign(
                binding=binding,
                cases=cases,
                repeats=REPEATS,
                probe_delay_seconds=0.0 if args.fake else 0.5,
            )
    except CampaignAbortedError as exc:
        status = f"aborted: {exc}"
        result = None
    summary: dict[str, Any] = {
        "source_commit": source_commit,
        "label": args.label,
        "started_at": started,
        "completed_at": datetime.now(UTC).isoformat(),
        "status": status,
        "attestation": attestation,
        "binding_digest": content_digest(asdict(binding.expected_binding)),
        "data_handling_policy_digest": binding.data_handling_policy_digest,
    }
    if result is not None:
        rows_text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in result["rows"])
        rows_path = args.evidence_dir / f"{args.label}-decisions.jsonl"
        _write_private(rows_path, rows_text)
        summary["decisions_digest"] = content_digest({"rows": rows_text})
        summary.update(judge(result["rows"], result["event_loop_lag_ms"]))
    summary_path = args.evidence_dir / f"{args.label}-summary.json"
    _write_private(summary_path, json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    printable = {key: value for key, value in summary.items() if key not in {"attestation"}}
    print("SUMMARY", json.dumps(printable, ensure_ascii=False))
    if result is None:
        return 2
    return 0 if summary["latency"]["passed"] and summary["window"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

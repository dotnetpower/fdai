#!/usr/bin/env python3
"""Run the fresh governed typed-selection answer-path protocols for #2034."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sys
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, cast

if __package__ is None or __package__ == "":
    _REPO_ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(_REPO_ROOT))
    sys.path.insert(0, str(_REPO_ROOT / "services/core-control-plane/src"))
    sys.path.insert(0, str(_REPO_ROOT / "packages/service-contracts/src"))

import httpx
from fdai.composition._helpers import Container
from fdai.composition.semantic_query_typed_selection_read import (
    bind_typed_selection_read,
    prepared_function_handler,
)
from fdai.composition.typed_selection_read import (
    GOVERNED_READ_CONFIG_RELATIVE_PATH,
    READ_DATA_POLICY,
    compose_typed_selection_read,
)
from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.typed_selection_contracts import (
    READ_FUNCTION,
    READ_QUALIFICATION_PURPOSE,
    ReadQualification,
)
from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
from fdai.delivery.catalog_search.ontology_governed_selection_campaign import (
    WINDOW_CASE_SET_V2,
    GovernedLatencyObservation,
    GovernedLatencyProtocolV2,
    GovernedWindowDecision,
    GovernedWindowProtocolV2,
    evaluate_governed_latency,
    evaluate_governed_window,
)
from fdai.delivery.catalog_search.ontology_governed_selection_read import (
    GovernedTypedSelectionRead,
    PreparedReadProposer,
    ReadSelectionSource,
    typed_read_source,
)
from fdai.delivery.catalog_search.ontology_selection_errors import (
    GovernedReadError,
    SelectionFailure,
)
from fdai.delivery.persistence.state_store_typed_selection_read import StateStoreTypedSelectionRead
from fdai.runtime.configuration import _model_endpoint_resolver
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai.shared.providers.direct_api import DirectApiOutcome, DirectApiReceipt
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.ontology_query import OntologyQueryNode, QueryNodeKind, content_digest
from scripts.evaluation.typed_selection_runtime_campaign import (
    LIVE_MIN_DECISION_START_INTERVAL_SECONDS,
    MAX_CONSECUTIVE_UNAVAILABLE,
    MAX_UNAVAILABLE,
    ROOT,
    TOTAL_DEADLINE_SECONDS,
    AdapterFailureLog,
    CampaignAbortedError,
    Case,
    _build_runtime,
    _context,
    _decision_pacing_delay,
    _fake_binding,
    _git,
    _load,
    _loop_lag,
    _prepare,
    _write_private,
)

_PROTOCOL_DIGEST = content_digest(
    {
        "latency": "governed-typed-selection-answer-latency.v2",
        "window": "governed-typed-selection-answer-window.v2",
        "case_set": WINDOW_CASE_SET_V2,
    }
)


class _CampaignAdmission:
    def __init__(self) -> None:
        self.qualification: ReadQualification | None = None

    async def admit(
        self,
        *,
        evidence_digest: str,
        scope_digest: str,
        purpose_id: str,
        source_revision: str,
    ) -> DecisionEvidenceAdmission | None:
        qualification = self.qualification
        if qualification is None or (
            evidence_digest != qualification.digest
            or scope_digest != qualification.binding.digest
            or purpose_id != READ_QUALIFICATION_PURPOSE
            or source_revision != qualification.binding.source_revision
        ):
            return None
        now = datetime.now(UTC)
        return DecisionEvidenceAdmission(
            receipt_digest=_PROTOCOL_DIGEST,
            verification_bundle_digest=_PROTOCOL_DIGEST,
            evidence_digest=evidence_digest,
            scope_digest=scope_digest,
            purpose_id=purpose_id,
            source_revision=source_revision,
            verified_at=now - timedelta(seconds=1),
            valid_until=now + timedelta(hours=2),
        )


class _CampaignApproval:
    async def load_replay(
        self, idempotency_key: str, request_fingerprint: str
    ) -> DirectApiReceipt | None:
        if (idempotency_key, request_fingerprint) != (
            "governed-campaign-approval",
            _PROTOCOL_DIGEST,
        ):
            return None
        return DirectApiReceipt(
            outcome=DirectApiOutcome.SUCCEEDED,
            receipt_ref=content_digest(
                {"idempotency_key": idempotency_key, "fingerprint": request_fingerprint}
            ),
        )


class _EvaluationRegistry(StateStoreTypedSelectionRead):
    """Disposable evaluation state, never the source harness or installation StateStore."""

    def __init__(self) -> None:
        self.campaign_admission = _CampaignAdmission()
        super().__init__(
            InMemoryStateStore(),
            admission=self.campaign_admission,
            approvals=_CampaignApproval(),
        )


def load_cases() -> tuple[Case, ...]:
    return tuple(
        Case(
            case_id=item["case_id"],
            query=item["query"],
            language=item["cohort"].split("-", 1)[0],
            expected=frozenset(item["expected_document_ids"]),
        )
        for item in _load(WINDOW_CASE_SET_V2)["cases"]
    )


def _runtime_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _container(values: Mapping[str, str]) -> Container:
    path_value = values["LLM_RESOLVED_MODELS_PATH"]
    path = Path(path_value)
    digest = (
        values.get("LLM_RESOLVED_MODELS_SHA256") or hashlib.sha256(path.read_bytes()).hexdigest()
    )
    return cast(
        Container,
        SimpleNamespace(
            resolved_models=None,
            resolved_models_artifact_digest=None,
            held_model_capabilities=frozenset(),
            decision_evidence_admission_provider=None,
            config=SimpleNamespace(
                llm=SimpleNamespace(
                    resolved_models_path=path_value,
                    resolved_models_sha256=digest,
                )
            ),
        ),
    )


async def _reader(
    *,
    runtime_env: Path | None,
    cases: Sequence[Case],
    harness: Any,
    source_revision: str,
) -> tuple[GovernedTypedSelectionRead, httpx.AsyncClient]:
    source: Callable[[FunctionInvocationContext], Awaitable[ReadSelectionSource]]
    if runtime_env is None:
        binding, http = _fake_binding(cases)
        proposer = cast(PreparedReadProposer, binding.proposer)
        workers = harness.runtime.workers
        if workers is None:
            await http.aclose()
            raise CampaignAbortedError("governed typed-selection source workers are unavailable")

        async def fake_source(context: FunctionInvocationContext) -> ReadSelectionSource:
            scope = await harness.runtime.enroll_context(context)
            return await typed_read_source(
                workers,
                scope,
                proposer=proposer,
                source_revision=source_revision,
                data_policy_digest=content_digest(READ_DATA_POLICY),
            )

        source = fake_source
    else:
        values = _runtime_values(runtime_env)
        endpoint = values.get("FDAI_LLM_ENDPOINT") or None
        http = httpx.AsyncClient(timeout=30)
        composed = compose_typed_selection_read(
            container=_container(values),
            environment={"FDAI_SOURCE_REVISION": source_revision},
            state_store=harness.state,
            index=harness.runtime,
            identity=AsyncAzureCliWorkloadIdentity.from_env(),
            http_client=http,
            endpoint=endpoint,
            endpoint_resolver=(
                _model_endpoint_resolver(endpoint, values.get("FDAI_MODEL_ENDPOINTS_JSON"))
                if endpoint is not None
                else None
            ),
            catalog_root=ROOT / "rule-catalog",
            config_path=ROOT / GOVERNED_READ_CONFIG_RELATIVE_PATH,
            owner_loop=asyncio.get_running_loop(),
        )
        source_resolver = composed.source
        if source_resolver is None or composed.proposer is None:
            await http.aclose()
            raise CampaignAbortedError("governed typed-selection live composition is unavailable")
        source = source_resolver
        proposer = composed.proposer
    registry = _EvaluationRegistry()
    return GovernedTypedSelectionRead(registry=registry, source=source, proposer=proposer), http


async def _activate_evaluation_pointer(
    reader: GovernedTypedSelectionRead,
    *,
    source_revision: str,
) -> dict[str, str]:
    registry = reader.registry
    if not isinstance(registry, _EvaluationRegistry):
        raise CampaignAbortedError("evaluation activation requires its disposable registry")
    if registry.campaign_admission.qualification is not None:
        raise CampaignAbortedError("evaluation activation cannot reuse a qualification")
    source_resolver = reader.source
    if source_resolver is None:
        raise CampaignAbortedError("governed typed-selection source is unavailable")
    source = await source_resolver(_context("governed-campaign-activation"))
    now = datetime.now(UTC)
    qualification = ReadQualification(
        binding=source.binding,
        outcome="qualified",
        qualification_evidence_digest=_PROTOCOL_DIGEST,
        answer_latency_evidence_digest=_PROTOCOL_DIGEST,
        issued_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(hours=2),
    )
    registry.campaign_admission.qualification = qualification
    await registry.save_qualification(qualification)
    pointer = await registry.promote(
        qualification_digest=qualification.digest,
        expected_revision=0,
        approval_key="governed-campaign-approval",
        approval_fingerprint=_PROTOCOL_DIGEST,
        request_digest=content_digest(
            {"source_revision": source_revision, "purpose": READ_QUALIFICATION_PURPOSE}
        ),
        actor="Thor",
    )
    return {
        "binding_digest": source.binding.digest,
        "qualification_digest": qualification.digest,
        "pointer_digest": pointer.digest,
        "model_binding_digest": source.binding.model_binding_digest,
    }


def _selected_ids(value: Mapping[str, object]) -> frozenset[str]:
    candidates = value.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("governed campaign result requires a candidate list")
    selected: set[str] = set()
    for item in candidates:
        if not isinstance(item, dict):
            raise ValueError("governed campaign candidate requires exact typed identity")
        object_type, object_id = item.get("object_type"), item.get("id")
        if (
            not isinstance(object_type, str)
            or not object_type
            or not isinstance(object_id, str)
            or not object_id
        ):
            raise ValueError("governed campaign candidate requires exact typed identity")
        identity = f"object:{object_type}:{object_id}"
        if identity in selected:
            raise ValueError("governed campaign candidate identities must be unique")
        selected.add(identity)
    return frozenset(selected)


def _adapter_failure(
    failures: AdapterFailureLog, before: Mapping[str, int]
) -> tuple[str | None, bool]:
    reasons: set[str] = set()
    for key, count in failures.counts.items():
        if count <= before.get(key, 0):
            continue
        fields = json.loads(key)
        kind = fields.get("failure_type")
        if fields.get("status_code") in {429, 503, "429", "503"}:
            reasons.add("provider_backpressure")
        elif kind in {
            "TimeoutError",
            "TimeoutException",
            "ReadTimeout",
            "ConnectTimeout",
            "WriteTimeout",
            "PoolTimeout",
        }:
            reasons.add("provider_timeout")
        elif kind == "HTTPStatusError":
            reasons.add("provider_http_error")
        elif kind in {"ValidationError", "SemanticPlanningResponseValidationError"}:
            reasons.add("proposal_contract_invalid")
        elif kind == "CandidateContextError":
            reasons.add("context_unavailable")
        else:
            reasons.add("adapter_unavailable")
    for reason in ("provider_backpressure", "provider_timeout"):
        if reason in reasons:
            return reason, True
    return min(reasons) if reasons else None, False


async def run_campaign(
    *,
    reader: GovernedTypedSelectionRead,
    harness: Any,
    cases: Sequence[Case],
    live: bool,
    failures: AdapterFailureLog,
) -> dict[str, object]:
    functions = OntologyFunctionRegistry(release=harness.release)
    bind_typed_selection_read(functions, harness.catalog, reader)
    rows: list[dict[str, object]] = []
    lag: list[float] = []
    stop = asyncio.Event()
    monitor = asyncio.create_task(_loop_lag(lag, stop))
    deadline = time.monotonic() + TOTAL_DEADLINE_SECONDS
    next_decision_start = time.monotonic()
    consecutive = unavailable = 0
    try:
        for repeat in range(1, 5):
            for case in cases:
                try:
                    delay = _decision_pacing_delay(
                        now=time.monotonic(),
                        next_start=next_decision_start,
                        deadline=deadline,
                    )
                except CampaignAbortedError as exc:
                    raise CampaignAbortedError(str(exc), rows=rows) from exc
                if delay and live:
                    await asyncio.sleep(delay)
                decision_started = time.monotonic()
                if decision_started >= deadline:
                    raise CampaignAbortedError("campaign total deadline exceeded", rows=rows)
                next_decision_start = decision_started + (
                    LIVE_MIN_DECISION_START_INTERVAL_SECONDS if live else 0.0
                )
                context = _context(f"governed:{case.case_id}:r{repeat}")
                node = OntologyQueryNode(
                    node_id=f"governed-{repeat}-{case.case_id}",
                    kind=QueryNodeKind.FUNCTION,
                    output_kind="query.candidates",
                    arguments_json=json.dumps(
                        {
                            "function_name": READ_FUNCTION,
                            "arguments": {"query": case.query, "limit": 20},
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                )
                failure_counts = dict(failures.counts)
                started = time.perf_counter()
                reason: str | None = None
                failure_reason: str | None = None
                selected: frozenset[str] = frozenset()
                outcome = "unavailable"
                try:
                    result = await prepared_function_handler(functions, context, reader)(node, {})
                    selected = _selected_ids(cast(Mapping[str, object], result.value))
                    outcome = "returned"
                except GovernedReadError as exc:
                    failure_reason = exc.reason.value
                    if exc.clarification:
                        outcome = "held"
                    else:
                        reason = "answer_unavailable"
                except (PermissionError, RuntimeError, TimeoutError, ValueError) as exc:
                    failure_reason = (
                        "read_timeout" if isinstance(exc, TimeoutError) else "unclassified"
                    )
                    reason = "answer_unavailable"
                adapter_reason, provider_stop = _adapter_failure(failures, failure_counts)
                if adapter_reason is not None:
                    failure_reason = adapter_reason
                    reason = (
                        "provider_unavailable"
                        if adapter_reason.startswith("provider_")
                        else "answer_unavailable"
                    )
                    outcome = "unavailable"
                latency_ms = (time.perf_counter() - started) * 1000
                provider_failure = reason == "provider_unavailable"
                consecutive = consecutive + 1 if provider_failure else 0
                unavailable += reason is not None
                rows.append(
                    {
                        "case_id": case.case_id,
                        "repeat": repeat,
                        "language": case.language,
                        "expected": sorted(case.expected),
                        "selected": sorted(selected),
                        "outcome": outcome,
                        "unavailable_reason": reason,
                        "failure_reason": failure_reason,
                        "latency_ms": latency_ms,
                    }
                )
                if provider_stop or failure_reason in {
                    SelectionFailure.PROPOSAL_TIMEOUT,
                    SelectionFailure.READ_TIMEOUT,
                    SelectionFailure.MEMBERSHIP_TIMEOUT,
                    SelectionFailure.FUNCTION_TIMEOUT,
                }:
                    raise CampaignAbortedError(
                        "provider backpressure or deadline ended the attempt", rows=rows
                    )
                if consecutive >= MAX_CONSECUTIVE_UNAVAILABLE or unavailable > MAX_UNAVAILABLE:
                    raise CampaignAbortedError(
                        "read unavailability exceeded the allowance", rows=rows
                    )
            print(f"repeat {repeat}/4 complete: {len(rows)} decisions", flush=True)
    finally:
        stop.set()
        await monitor
    return {"rows": rows, "event_loop_lag_ms": lag}


def judge(rows: Sequence[Mapping[str, object]], lag: Sequence[float]) -> dict[str, object]:
    latency = evaluate_governed_latency(
        [
            GovernedLatencyObservation(
                latency_ms=float(cast(float, row["latency_ms"])),
                unavailable_reason=(
                    str(row["unavailable_reason"])
                    if row["unavailable_reason"] is not None
                    else None
                ),
            )
            for row in rows
        ],
        lag,
        protocol=GovernedLatencyProtocolV2(),
    )
    window = evaluate_governed_window(
        [
            GovernedWindowDecision(
                case_id=str(row["case_id"]),
                language=str(row["language"]),
                expected=frozenset(cast(Sequence[str], row["expected"])),
                outcome=cast(Literal["returned", "held", "unavailable"], row["outcome"]),
                selected=frozenset(cast(Sequence[str], row["selected"])),
            )
            for row in rows
        ],
        protocol=GovernedWindowProtocolV2(),
    )
    return {
        "latency": asdict(latency) | {"passed": latency.passed},
        "window": asdict(window) | {"passed": window.passed},
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--runtime-env", type=Path)
    parser.add_argument("--fake", action="store_true")
    args = parser.parse_args()
    if args.fake == (args.runtime_env is not None):
        parser.error("choose exactly one of --fake or --runtime-env")
    if not args.fake:
        parser.error(
            "governed v1/v2 windows are spent; live qualification requires a fresh independently "
            "authored, reviewed and deduplicated protocol"
        )
    if _git("status", "--porcelain", "--untracked-files=no"):
        raise SystemExit("tracked worktree must be clean")
    source_commit = _git("rev-parse", "HEAD")
    cases = load_cases()
    harness = await _build_runtime(None, governed_read=True)
    await _prepare(harness.runtime, harness.state)
    reader, http = await _reader(
        runtime_env=args.runtime_env,
        cases=cases,
        harness=harness,
        source_revision=source_commit,
    )
    activation = await _activate_evaluation_pointer(reader, source_revision=source_commit)
    args.evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    failures = AdapterFailureLog()
    logging.getLogger("fdai.delivery.azure.llm").addHandler(failures)
    started = datetime.now(UTC).isoformat()
    status = "completed"
    partial: Sequence[Mapping[str, object]] = ()
    try:
        async with http:
            result = await run_campaign(
                reader=reader,
                harness=harness,
                cases=cases,
                live=not args.fake,
                failures=failures,
            )
    except CampaignAbortedError as exc:
        status = f"aborted: {exc}"
        result = None
        partial = exc.rows
    rows = cast(Sequence[Mapping[str, object]], result["rows"] if result else partial)
    decisions = args.evidence_dir / "decisions.jsonl"
    text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    _write_private(decisions, text)
    summary: dict[str, object] = {
        "source_commit": source_commit,
        "label": args.label,
        "started_at": started,
        "completed_at": datetime.now(UTC).isoformat(),
        "status": status,
        **activation,
        "adapter_failures": dict(failures.counts),
        "completed_decisions": len(rows),
        "decisions_digest": "sha256:" + hashlib.sha256(text.encode()).hexdigest(),
        "evaluation_pointer_persistent": False,
        "evidence_scope": "isolated_evaluation_only",
        "independent_qualification_admission": False,
        "current_owner_approval": False,
        "production_qualification": False,
        "execution_authority": False,
    }
    if result is not None:
        summary.update(judge(rows, cast(Sequence[float], result["event_loop_lag_ms"])))
    _write_private(
        args.evidence_dir / "summary.json",
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
    )
    print("SUMMARY " + json.dumps(summary, ensure_ascii=False), flush=True)
    if result is None:
        return 2
    passed = all(
        cast(Mapping[str, object], summary[key])["passed"] for key in ("latency", "window")
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

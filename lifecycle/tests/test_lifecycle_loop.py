"""The Hub-agent lifecycle loop, end to end on loopback (#1952).

Each scenario drives the real Hub command line and API and the real agent command line: enroll,
approve, prove ownership, manage, recompute, poll, and report. The Hub API runs in a loopback
thread and the agent polls it over HTTP. Keys are generated per test; none is committed. Run every
scenario from the repository root with one command:

    uv run --no-sync pytest -c pyproject.toml lifecycle/tests -q

Set ``FDAI_DATABASE_URL`` to also run the scenarios against loopback PostgreSQL.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import pytest
import uvicorn
from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.lifecycle_plan import decode_canonical_plan_payload
from fdai_deployment_cli.runtime_release import parse_runtime_release_manifest

from fdai_lifecycle_agent import cli as agent_cli
from fdai_lifecycle_agent.hub_client import (
    HttpHubClient,
    HubProtocolError,
    PlanReport,
    SignedPlan,
)
from fdai_lifecycle_agent.journal import WorkloadState, WorkloadStore
from fdai_lifecycle_agent.state import (
    AgentState,
    AgentStateError,
    LocalStateStore,
    PlanRecord,
    PlanResult,
    StoredReport,
)
from fdai_lifecycle_agent.workload import Cluster, Manifest
from fdai_lifecycle_hub import cli as hub_cli
from fdai_lifecycle_hub.api import create_app
from fdai_lifecycle_hub.signing import key_id_for, load_private_key, load_public_key
from fdai_lifecycle_hub.store import HubStore

SAMPLES = Path(__file__).resolve().parents[1] / "hub" / "samples"
INSTALLATION_ID = "example"
TARGET = "1.6.0"
FIRST_PLAN = f"{INSTALLATION_ID}-00000001"
SECOND_PLAN = f"{INSTALLATION_ID}-00000002"
_CREDENTIAL_PREFIXES = ("AZURE_", "ARM_", "MSI_", "IDENTITY_")

type ConnectHub = Callable[[str, float], HttpHubClient]


@dataclass
class RecordingCluster:
    """A mechanical Kubernetes seam that distinguishes dry runs from mutations."""

    namespace: str = "fdai-demo"
    dry_runs: list[tuple[str, str]] = field(default_factory=list)
    mutations: list[tuple[str, str, str]] = field(default_factory=list)

    def apply(self, manifest: Manifest, *, dry_run: bool = False) -> None:
        key = (str(manifest["kind"]), str(manifest["metadata"]["name"]))
        if dry_run:
            self.dry_runs.append(key)
        else:
            self.mutations.append(("apply", *key))

    def get(self, kind: str, name: str) -> Manifest | None:
        return None

    def delete(self, kind: str, name: str) -> None:
        self.mutations.append(("delete", kind, name))


class MisroutedHub(HttpHubClient):
    """A network path that delivers this agent's requests to the `example` installation."""

    def fetch_plan(self, installation_id: str) -> SignedPlan | None:
        return super().fetch_plan(INSTALLATION_ID)

    def submit_report(self, installation_id: str, plan_id: str, report: PlanReport) -> None:
        super().submit_report(INSTALLATION_ID, plan_id, report)


def connect(url: str, timeout: float) -> HttpHubClient:
    return HttpHubClient(url, timeout_seconds=timeout)


def misrouted(url: str, timeout: float) -> HttpHubClient:
    return MisroutedHub(url, timeout_seconds=timeout)


def replaying(plan: SignedPlan) -> ConnectHub:
    """A network path that serves `plan` again instead of the Hub's open Plan."""

    class ReplayingHub(HttpHubClient):
        def fetch_plan(self, installation_id: str) -> SignedPlan | None:
            return plan

    return lambda url, timeout: ReplayingHub(url, timeout_seconds=timeout)


@dataclass(frozen=True, slots=True)
class Loop:
    """One Hub and its agents, wired through the files under `root`."""

    root: Path
    hub_url: str

    def hub(self, *args: str) -> dict[str, Any]:
        output = io.StringIO()
        with redirect_stdout(output):
            assert hub_cli.main(args) == 0, args
        record: dict[str, Any] = json.loads(output.getvalue())
        return record

    def enroll(self, template: dict[str, Any]) -> None:
        """Enroll and approve the installation, then manage its `core` Entity."""

        path = self.root / "enrollment.json"
        path.write_text(json.dumps(template))
        pending = self.hub("dev-enroll", str(path), "--key", str(self.root / "installation.pem"))
        key_id = pending["installation_key_id"]
        self.hub("approve", INSTALLATION_ID, "--approver", "alice", "--installation-key-id", key_id)
        ownership = str(SAMPLES / "ownership.json")
        settings = str(SAMPLES / "core-settings.json")
        self.hub("record-ownership", INSTALLATION_ID, "core", ownership, "--operator", "bob")
        self.hub("manage", INSTALLATION_ID, "core", settings, "--operator", "bob")

    def recompute(self) -> dict[str, Any]:
        catalog = str(SAMPLES / "catalog")
        return self.hub(
            "recompute", INSTALLATION_ID, "--catalog", catalog, "--key", str(self.root / "hub.pem")
        )

    def show(self) -> dict[str, Any]:
        return self.hub("show", INSTALLATION_ID)

    def poll(
        self,
        installation_id: str = INSTALLATION_ID,
        *,
        connect_hub: ConnectHub = connect,
        clock: Callable[[], datetime] | None = None,
        cluster: Cluster | None = None,
        expected_exit_code: int = 0,
    ) -> dict[str, Any]:
        hub_public_key = self.root / "hub.pub.pem"
        argv = [
            "poll-once",
            *("--hub-url", self.hub_url),
            *("--installation-id", installation_id),
            *("--state-dir", str(self.root / "state" / installation_id)),
            *("--hub-public-key", str(hub_public_key)),
            *("--hub-key-id", key_id_for(load_public_key(hub_public_key))),
            *("--hub-key-epoch", "1"),
            *("--fencing-generation", "1"),
            *("--release-public-key", str(self.root / "release.pub.pem")),
            *("--configuration-public-key", str(self.root / "configuration.pub.pem")),
            *("--inputs-dir", str(self.root / "inputs")),
            *("--current-state", str(self.root / "current-state.json")),
            *("--local-policy", str(self.root / "local-policy.json")),
        ]
        if cluster is not None:
            argv.extend(["--apply", "--kube-context", "integration", "--namespace", "fdai-demo"])

        def connect_cluster(context: str, namespace: str) -> Cluster:
            assert cluster is not None
            assert (context, namespace) == ("integration", "fdai-demo")
            return cluster

        effective_clock = clock or (lambda: datetime.now(UTC))
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = agent_cli.main(
                argv,
                connect_hub=connect_hub,
                connect_cluster=connect_cluster,
                clock=effective_clock,
            )
            assert exit_code == expected_exit_code
        rendered = output.getvalue()
        if not rendered:
            assert expected_exit_code != 0
            return {}
        result: dict[str, Any] = json.loads(rendered)
        return result


def sample() -> dict[str, Any]:
    enrollment: dict[str, Any] = json.loads((SAMPLES / "enrollment.json").read_bytes())
    return enrollment


def with_window(*, starts_in: timedelta, duration: str) -> dict[str, Any]:
    """The sample enrollment request with one daily UTC window that starts relative to now."""

    template = sample()
    start = (datetime.now(UTC) + starts_in).time().replace(microsecond=0)
    template["settings"]["windows"] = [
        {"start": start.isoformat(), "duration": duration, "timezone": "UTC"}
    ]
    return template


def open_window() -> dict[str, Any]:
    return with_window(starts_in=timedelta(hours=-1), duration="PT12H")


def reports(shown: dict[str, Any]) -> list[tuple[str, str, str, str | None]]:
    return [
        (r["plan_id"], r["outcome"], r["reason_code"], r["exact_plan_digest"])
        for r in shown["reports"]
    ]


def block_reasons(record: dict[str, Any]) -> list[tuple[str, list[str]]]:
    return [
        (check["release_id"], [block["reason_code"] for block in check["blocks"]])
        for check in record["checks"]
    ]


@pytest.fixture
def no_azure_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove Azure credential variables before the Hub store, API, or agent is created."""

    for name in [n for n in os.environ if n.startswith(_CREDENTIAL_PREFIXES)]:
        monkeypatch.delenv(name)


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.integration)])
def database_url(
    request: pytest.FixtureRequest, tmp_path: Path, no_azure_credentials: None
) -> Iterator[str]:
    if request.param == "sqlite":
        yield f"sqlite+pysqlite:///{tmp_path / 'hub.db'}"
        return
    url: str = request.getfixturevalue("loopback_postgres_url")
    store = HubStore.connect(url)
    store.drop_schema()
    yield url
    store.drop_schema()
    store.engine.dispose()


@pytest.fixture
def hub_url(database_url: str) -> Iterator[str]:
    """Serve the Hub API on an ephemeral loopback port for the duration of one test."""

    store = HubStore.connect(database_url)
    config = uvicorn.Config(create_app(store), host=hub_cli.LOOPBACK, port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            pytest.fail("the Hub API did not start")
        time.sleep(0.01)
    (socket,) = server.servers[0].sockets
    yield f"http://{hub_cli.LOOPBACK}:{socket.getsockname()[1]}"
    server.should_exit = True
    thread.join(timeout=10)
    store.engine.dispose()


@pytest.fixture
def loop(tmp_path: Path, database_url: str, hub_url: str, monkeypatch: pytest.MonkeyPatch) -> Loop:
    """A migrated Hub, development keys, and the agent's signed inputs and local files."""

    monkeypatch.setenv(hub_cli.DATABASE_URL_ENV, database_url)
    loop = Loop(tmp_path, hub_url)
    loop.hub("migrate")
    for key in ("hub", "installation", "release", "configuration"):
        loop.hub("dev-keygen", str(tmp_path / f"{key}.pem"))

    enrollment = sample()
    release = (SAMPLES / "catalog" / "releases" / f"{TARGET}.json").read_bytes()
    signed = {
        ("release", parse_runtime_release_manifest(release).digest): release,
        ("configuration", canonical_digest(enrollment["configuration"])): canonical_bytes(
            enrollment["configuration"]
        ),
    }
    for (kind, digest), payload in signed.items():
        directory = tmp_path / "inputs" / f"{kind}s"
        directory.mkdir(parents=True)
        (directory / f"{digest}.json").write_bytes(payload)
        signature = load_private_key(tmp_path / f"{kind}.pem").sign(payload)
        (directory / f"{digest}.sig").write_bytes(signature)

    # The agent's current state is the snapshot the installation reported when it enrolled.
    (tmp_path / "current-state.json").write_text(json.dumps(enrollment["reported"]))
    local_policy = {
        "schema": agent_cli.LOCAL_POLICY_SCHEMA,
        "entity_ids": ["core"],
        "regions": [enrollment["settings"]["region"]],
        "capability_modes": {"action:scale-service": "enforce"},
        "destructive_allowed": False,
        "max_duration_minutes": 60,
        "entity_components": {"core": ["core-control-plane"]},
    }
    (tmp_path / "local-policy.json").write_text(json.dumps(local_policy))
    return loop


def test_happy_path_admits_the_plan_and_the_hub_records_the_report(loop: Loop) -> None:
    loop.enroll(open_window())

    issued = loop.recompute()
    result = loop.poll()
    shown = loop.show()

    assert (issued["outcome"], issued["plan_id"], issued["target"]) == (
        "issued",
        FIRST_PLAN,
        TARGET,
    )
    assert block_reasons(issued) == [(TARGET, [])]
    assert (result["outcome"], result["reason_code"], result["plan_id"], result["reported"]) == (
        "dry-run-admitted",
        "dry_run_computed",
        FIRST_PLAN,
        True,
    )
    assert shown["plan"]["plan_id"] == FIRST_PLAN
    assert block_reasons(shown["last_evaluation"]) == [(TARGET, [])]
    assert reports(shown) == [
        (FIRST_PLAN, "dry-run-admitted", "dry_run_computed", result["exact_plan_digest"])
    ]
    assert shown["reports"][0]["summary"]


def test_unsigned_release_is_rejected_and_the_hub_records_why(loop: Loop) -> None:
    for signature in (loop.root / "inputs" / "releases").glob("*.sig"):
        signature.unlink()
    loop.enroll(open_window())
    loop.recompute()

    result = loop.poll()

    assert (result["outcome"], result["reason_code"], result["reported"]) == (
        "rejected",
        "release_signature_missing",
        True,
    )
    assert reports(loop.show()) == [(FIRST_PLAN, "rejected", "release_signature_missing", None)]


def test_final_agent_report_survives_a_backward_client_clock(loop: Loop) -> None:
    release = next((loop.root / "inputs" / "releases").glob("*.json"))
    release_bytes = release.read_bytes()
    release.unlink()
    loop.enroll(open_window())
    loop.recompute()
    first_clock = datetime.now(UTC) + timedelta(seconds=10)

    first = loop.poll(clock=lambda: first_clock)
    release.write_bytes(release_bytes)
    final = loop.poll(clock=lambda: first_clock - timedelta(seconds=20))
    shown = loop.show()

    assert (first["reason_code"], first["reported"]) == ("release_unavailable", True)
    assert (final["outcome"], final["reported"]) == ("dry-run-admitted", True)
    assert [(report["attempt"], report["outcome"]) for report in shown["reports"]] == [
        (1, "rejected"),
        (2, "dry-run-admitted"),
    ]
    assert shown["reports"][1]["reported_at"] < shown["reports"][0]["reported_at"]


def test_retryable_terminal_gap_replays_complete_prefix_across_agent_restarts(
    loop: Loop,
) -> None:
    loop.enroll(open_window())
    loop.recompute()
    with HttpHubClient(loop.hub_url) as client:
        signed = client.fetch_plan(INSTALLATION_ID)
    assert signed is not None
    plan = decode_canonical_plan_payload(signed.signed_payload, signed.signature)
    payload_digest = hashlib.sha256(signed.signed_payload).hexdigest()
    exact_digest = f"sha256:{payload_digest}"
    terminal_time = datetime.now(UTC)
    started_result = PlanResult(
        outcome="apply-started",
        reason_code="apply_started",
        exact_plan_digest=exact_digest,
        summary='{"update":1}',
    )
    terminal_result = PlanResult(
        outcome="applied",
        reason_code="applied",
        exact_plan_digest=exact_digest,
        summary='{"update":1}',
    )
    retryable_result = PlanResult(
        outcome="rejected",
        reason_code="release_unavailable",
        retryable=True,
    )
    history = (
        StoredReport(
            attempt=1,
            result=retryable_result,
            reported_at=terminal_time - timedelta(seconds=2),
        ),
        StoredReport(
            attempt=2,
            result=started_result,
            reported_at=terminal_time - timedelta(seconds=1),
        ),
        StoredReport(
            attempt=3,
            result=terminal_result,
            reported_at=terminal_time,
        ),
    )
    state_store = LocalStateStore(loop.root / "state" / INSTALLATION_ID)
    state_store.save(
        AgentState(
            last_accepted_sequence=plan.sequence,
            plans={
                plan.plan_id: PlanRecord(
                    sequence=plan.sequence,
                    payload_digest=payload_digest,
                    result=terminal_result,
                    attempts=3,
                    reported_at=terminal_time,
                    apply_started_report=StoredReport(
                        attempt=2,
                        result=started_result,
                        reported_at=terminal_time - timedelta(seconds=1),
                    ),
                    report_history=history,
                )
            },
        )
    )

    gap = loop.poll(expected_exit_code=1)
    assert loop.show()["reports"] == []
    retryable = loop.poll(expected_exit_code=1)
    pending_after_restart = state_store.load().plans[plan.plan_id].pending_reports
    started = loop.poll(expected_exit_code=1)
    terminal = loop.poll()
    shown = loop.show()

    assert [
        (result["outcome"], result["reported"]) for result in (gap, retryable, started, terminal)
    ] == [
        ("applied", False),
        ("applied", False),
        ("applied", False),
        ("applied", True),
    ]
    assert [report.attempt for report in pending_after_restart] == [2, 3]
    assert [(report["attempt"], report["outcome"]) for report in shown["reports"]] == [
        (1, "rejected"),
        (2, "apply-started"),
        (3, "applied"),
    ]
    assert state_store.load().plans[plan.plan_id].pending_reports == ()


@pytest.mark.parametrize("outcome", ["apply-started", "rejected"])
def test_hub_rejects_invalid_agent_report_after_apply_started(
    loop: Loop, outcome: Literal["apply-started", "rejected"]
) -> None:
    loop.enroll(open_window())
    loop.recompute()
    with HttpHubClient(loop.hub_url) as client:
        signed = client.fetch_plan(INSTALLATION_ID)
        assert signed is not None
        exact_digest = f"sha256:{hashlib.sha256(signed.signed_payload).hexdigest()}"
        reported_at = datetime.now(UTC)
        client.submit_report(
            INSTALLATION_ID,
            FIRST_PLAN,
            PlanReport(
                attempt=1,
                outcome="apply-started",
                reason_code="apply_started",
                exact_plan_digest=exact_digest,
                summary='{"update":1}',
                reported_at=reported_at,
            ),
        )
        invalid = PlanReport(
            attempt=2,
            outcome=outcome,
            reason_code="invalid_successor",
            exact_plan_digest=exact_digest if outcome == "apply-started" else None,
            summary='{"update":1}',
            reported_at=reported_at + timedelta(seconds=1),
        )

        with pytest.raises(HubProtocolError, match="422 report_invalid") as error:
            client.submit_report(INSTALLATION_ID, FIRST_PLAN, invalid)

    assert error.value.code == "report_invalid"
    assert [(report["attempt"], report["outcome"]) for report in loop.show()["reports"]] == [
        (1, "apply-started")
    ]


@pytest.mark.parametrize(
    "fault_boundary",
    [
        "terminal-persist",
        "hub-acceptance",
        "acceptance-persist",
        "journal-clear",
    ],
)
def test_expiry_faults_restart_to_terminal_without_kubernetes_mutation(
    loop: Loop,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    fault_boundary: str,
) -> None:
    loop.enroll(open_window())
    loop.recompute()
    with HttpHubClient(loop.hub_url) as client:
        signed = client.fetch_plan(INSTALLATION_ID)
    assert signed is not None
    plan = decode_canonical_plan_payload(signed.signed_payload, signed.signature)
    local_policy = json.loads((loop.root / "local-policy.json").read_text())
    local_policy["component_images"] = {"core-control-plane": "registry.example.test/fdai/core"}
    (loop.root / "local-policy.json").write_text(json.dumps(local_policy))
    cluster = RecordingCluster()

    def expire_only_after_started_is_accepted() -> datetime:
        accepted = any(report["outcome"] == "apply-started" for report in loop.show()["reports"])
        offset = timedelta(seconds=1)
        return plan.expires_at + offset if accepted else plan.expires_at - offset

    injected = False
    original_state_save = LocalStateStore.save
    original_workload_save = WorkloadStore.save

    def fail_state_save(store: LocalStateStore, state: AgentState) -> None:
        nonlocal injected
        record = state.plans.get(plan.plan_id)
        if record is None:
            original_state_save(store, state)
            return
        terminal = record.result.reason_code == "plan_expired"
        at_boundary = (
            fault_boundary == "terminal-persist"
            and terminal
            and not record.reported
            and record.reported_at is not None
        ) or (fault_boundary == "acceptance-persist" and terminal and record.reported)
        if at_boundary and not injected:
            injected = True
            raise AgentStateError(f"injected {fault_boundary} failure")
        original_state_save(store, state)

    def fail_workload_save(store: WorkloadStore, state: WorkloadState) -> None:
        nonlocal injected
        if fault_boundary == "journal-clear" and state.journal is None and not injected:
            injected = True
            raise AgentStateError("injected journal-clear failure")
        original_workload_save(store, state)

    class LostTerminalAcceptance(HttpHubClient):
        def submit_report(self, installation_id: str, plan_id: str, report: PlanReport) -> None:
            nonlocal injected
            super().submit_report(installation_id, plan_id, report)
            if (
                fault_boundary == "hub-acceptance"
                and report.reason_code == "plan_expired"
                and not injected
            ):
                injected = True
                raise HubProtocolError("injected lost terminal acceptance")

    monkeypatch.setattr(LocalStateStore, "save", fail_state_save)
    monkeypatch.setattr(WorkloadStore, "save", fail_workload_save)

    def connect_with_fault(url: str, timeout: float) -> HttpHubClient:
        if fault_boundary == "hub-acceptance":
            return LostTerminalAcceptance(url, timeout_seconds=timeout)
        return connect(url, timeout)

    failed = loop.poll(
        clock=expire_only_after_started_is_accepted,
        cluster=cluster,
        connect_hub=connect_with_fault,
        expected_exit_code=1,
    )
    assert injected
    assert failed == {} or failed["reported"] is False
    retained = WorkloadStore(loop.root / "state" / INSTALLATION_ID).load().journal
    assert retained is not None and retained.phase == "prepared"

    restarted = loop.poll(clock=expire_only_after_started_is_accepted, cluster=cluster)
    shown = loop.show()
    store = HubStore.connect(database_url)
    try:
        suppressions = store.load(INSTALLATION_ID).suppressions
    finally:
        store.engine.dispose()

    assert restarted["outcome"] in {"rejected", "already-reported"}
    assert (restarted["reason_code"], restarted["reported"]) == ("plan_expired", True)
    assert cluster.dry_runs
    assert cluster.mutations == []
    assert WorkloadStore(loop.root / "state" / INSTALLATION_ID).load().journal is None
    terminal_reports = [
        (report["attempt"], report["outcome"], report["reason_code"]) for report in shown["reports"]
    ]
    assert terminal_reports == [
        (1, "apply-started", "apply_started"),
        (2, "rejected", "plan_expired"),
    ]
    assert suppressions == ()


def test_plan_for_another_installation_is_rejected_and_the_hub_records_why(loop: Loop) -> None:
    loop.enroll(open_window())
    loop.recompute()

    result = loop.poll("other", connect_hub=misrouted)

    assert (result["outcome"], result["reason_code"], result["plan_id"]) == (
        "rejected",
        "plan_audience_mismatch",
        FIRST_PLAN,
    )
    assert reports(loop.show()) == [(FIRST_PLAN, "rejected", "plan_audience_mismatch", None)]


def test_replayed_sequence_is_rejected_and_the_hub_records_why(loop: Loop) -> None:
    loop.enroll(open_window())
    loop.recompute()
    with HttpHubClient(loop.hub_url) as client:
        first = client.fetch_plan(INSTALLATION_ID)
    assert first is not None
    # A suppression supersedes the first Plan; lifting it issues the next sequence.
    loop.hub("suppress", INSTALLATION_ID, "--minutes", "5")
    assert loop.recompute()["outcome"] == "waiting"
    loop.hub("unsuppress", INSTALLATION_ID)
    assert loop.recompute()["plan_id"] == SECOND_PLAN
    admitted = loop.poll()

    replayed = loop.poll(connect_hub=replaying(first))

    assert (admitted["outcome"], admitted["plan_id"]) == ("dry-run-admitted", SECOND_PLAN)
    assert (replayed["outcome"], replayed["reason_code"], replayed["plan_id"]) == (
        "rejected",
        "plan_sequence_stale",
        FIRST_PLAN,
    )
    assert reports(loop.show()) == [
        (SECOND_PLAN, "dry-run-admitted", "dry_run_computed", admitted["exact_plan_digest"]),
        (FIRST_PLAN, "rejected", "plan_sequence_stale", None),
    ]


def test_outside_every_window_the_hub_issues_no_plan_and_records_the_block(loop: Loop) -> None:
    loop.enroll(with_window(starts_in=timedelta(hours=12), duration="PT1M"))

    waiting = loop.recompute()
    result = loop.poll()
    shown = loop.show()

    assert (waiting["outcome"], waiting["target"]) == ("waiting", TARGET)
    assert block_reasons(waiting) == [(TARGET, ["maintenance_window_unavailable"])]
    assert (result["outcome"], result["reported"]) == ("no-plan", False)
    assert shown["plan"] is None
    assert block_reasons(shown["last_evaluation"]) == [(TARGET, ["maintenance_window_unavailable"])]
    assert shown["reports"] == []

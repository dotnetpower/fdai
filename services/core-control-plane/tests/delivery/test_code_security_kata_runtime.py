"""Kata Jobs have no credentials; authenticated API observations govern process completion."""

from __future__ import annotations

import copy
import json
import ssl
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fdai.delivery.code_security_kata_client import InClusterKataClient, KataApiError
from fdai.delivery.code_security_kata_job import (
    KataScanConfig,
    build_scanner_job,
    validate_scanner_pod,
)
from fdai.delivery.code_security_kata_sandbox import KataScannerSandbox
from fdai.rule_catalog.code_security_scanners import ScannerSpec


def _config(tmp_path: Path, **kwargs: object) -> KataScanConfig:
    return KataScanConfig(
        namespace="code-security",
        image="example/scanner@sha256:" + "a" * 64,
        source_pvc="source",
        source_mount=tmp_path,
        **kwargs,
    )


def _spec() -> ScannerSpec:
    return ScannerSpec.model_validate(
        {
            "producer": "Opengrep",
            "argv": ["scan", "{source}"],
            "success_exit_codes": [0],
            "timeout_seconds": 10,
            "max_output_bytes": 1000,
        }
    )


class _Client(InClusterKataClient):
    def __init__(self, *, mutation: str = "") -> None:
        self.mutation = mutation
        self.job: dict[str, object] = {}
        self.uid = "job-uid"
        self.deleted = False
        self.calls: list[tuple[str, str]] = []
        self.pod_reads = 0

    async def request(self, method: str, path: str, *, body=None):  # type: ignore[no-untyped-def]
        self.calls.append((method, path))
        if "networkpolicies" in path:
            result = {
                "items": [
                    {
                        "metadata": {"name": "fdai-code-security-deny-all"},
                        "spec": {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]},
                    }
                ]
            }
            if self.mutation == "allow-network":
                result["items"].append(
                    {
                        "metadata": {"name": "unexpected-allow"},
                        "spec": {"egress": [{}]},
                    }
                )
            return result
        if "runtimeclasses" in path:
            return {"handler": "runc" if self.mutation == "runc" else "kata-vm-isolation"}
        if path == "/api/v1/namespaces/code-security":
            return {
                "metadata": {
                    "labels": {
                        "pod-security.kubernetes.io/enforce": "privileged"
                        if self.mutation == "privileged-namespace"
                        else "restricted",
                    }
                }
            }
        if method == "POST":
            self.job = copy.deepcopy(body)
            return {"metadata": {"name": body["metadata"]["name"], "uid": self.uid}}
        if method == "DELETE":
            assert body["preconditions"]["uid"] == self.uid
            if self.mutation == "cleanup-failed":
                raise KataApiError("Kubernetes operation failed with HTTP 503")
            self.deleted = True
            return {"status": "Success"}
        if "/pods?" in path:
            self.pod_reads += 1
            pod = copy.deepcopy(self.job["spec"]["template"])
            pod["metadata"] = {
                "name": "scanner-pod",
                "uid": "scanner-pod-uid",
                "ownerReferences": [{"uid": self.uid, "controller": True}],
            }
            pod["status"] = {
                "containerStatuses": [
                    {
                        "name": "scanner",
                        "restartCount": 0,
                        "state": {
                            "terminated": {"exitCode": 1 if self.mutation == "exit-failed" else 0},
                        },
                    }
                ]
            }
            spec = pod["spec"]
            if self.mutation == "image":
                spec["containers"][0]["image"] = "example/other:latest"
            elif self.mutation == "token":
                spec["automountServiceAccountToken"] = True
            elif self.mutation == "extra-container":
                spec["initContainers"] = [{"name": "credential-injector"}]
            elif self.mutation == "secret":
                spec["volumes"].append({"name": "credential", "secret": {"secretName": "example"}})
            elif self.mutation == "uid":
                pod["metadata"]["ownerReferences"][0]["uid"] = "another-job"
            elif self.mutation == "privilege":
                spec["containers"][0]["securityContext"]["allowPrivilegeEscalation"] = True
            elif self.mutation == "resource":
                spec["containers"][0]["resources"]["limits"]["memory"] = "8Gi"
            elif self.mutation == "quantity-normalization":
                spec["containers"][0]["resources"]["limits"]["memory"] = "4Gi"
                spec["containers"][0]["resources"]["requests"]["memory"] = "4Gi"
            elif self.mutation == "missing-false-default":
                for field in ("hostNetwork", "hostPID", "hostIPC"):
                    spec.pop(field)
            elif self.mutation == "job-no-pod":
                return {"items": []}
            elif self.mutation == "quiet-running" and self.pod_reads < 3:
                pod["status"]["containerStatuses"][0]["state"] = {"running": {"startedAt": "test"}}
            elif self.mutation == "pod-uid-change":
                if self.pod_reads == 1:
                    pod["status"]["containerStatuses"][0]["state"] = {
                        "running": {"startedAt": "test"}
                    }
                else:
                    pod["metadata"]["uid"] = "replacement-pod"
            return {"items": [pod]}
        return {
            "metadata": {
                "uid": "another-job" if self.mutation == "job-uid" else self.uid,
            }
        }

    async def stdout(self, namespace: str, pod_name: str, limit: int) -> tuple[bytes, bool]:
        assert namespace == "code-security" and pod_name == "scanner-pod"
        return (
            b'{"version":"2.1.0","runs":[{"tool":{"driver":{"name":"Opengrep",'
            b'"version":"1"}},"results":[]}]}',
            self.mutation == "truncated",
        )

    async def aclose(self) -> None:
        pass


@pytest.mark.parametrize("mutation", ["", "quantity-normalization", "missing-false-default"])
async def test_external_process_observation_accepts_only_the_bound_pod(
    tmp_path: Path, mutation: str
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    client = _Client(mutation=mutation)
    sandbox = KataScannerSandbox(_config(tmp_path), client)
    result = await sandbox.run("opengrep", _spec(), Path("/opt/scanners/bin/opengrep"), source)
    assert result.completed and result.exit_code == 0
    assert client.deleted and sandbox.observations == (result,)
    job = client.job
    pod = job["spec"]["template"]["spec"]
    assert pod["runtimeClassName"] == "kata-vm-isolation"
    assert pod["automountServiceAccountToken"] is False
    assert pod["containers"][0]["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
    assert not any("secret" in volume for volume in pod["volumes"])


@pytest.mark.parametrize(
    "mutation",
    [
        "image",
        "token",
        "extra-container",
        "secret",
        "uid",
        "privilege",
        "resource",
        "job-uid",
    ],
)
async def test_mismatched_remote_execution_is_denied_and_cleaned(
    tmp_path: Path, mutation: str
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    client = _Client(mutation=mutation)
    sandbox = KataScannerSandbox(_config(tmp_path), client)
    with pytest.raises((ValueError, KataApiError)):
        await sandbox.run("opengrep", _spec(), Path("/opt/scanners/bin/opengrep"), source)
    assert client.deleted and not sandbox.observations


@pytest.mark.parametrize("mutation", ["allow-network", "runc", "privileged-namespace"])
async def test_missing_isolation_prevents_job_creation(tmp_path: Path, mutation: str) -> None:
    source = tmp_path / "source"
    source.mkdir()
    client = _Client(mutation=mutation)
    sandbox = KataScannerSandbox(_config(tmp_path), client)
    with pytest.raises(KataApiError):
        await sandbox.run("opengrep", _spec(), Path("/opt/scanners/bin/opengrep"), source)
    assert not any(method == "POST" for method, _ in client.calls)


@pytest.mark.parametrize("mutation", ["exit-failed", "truncated"])
async def test_failure_or_truncation_is_never_a_complete_scan(
    tmp_path: Path, mutation: str
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    client = _Client(mutation=mutation)
    result = await KataScannerSandbox(_config(tmp_path), client).run(
        "opengrep", _spec(), Path("/opt/scanners/bin/opengrep"), source
    )
    assert not result.completed and client.deleted


async def test_job_failure_has_a_private_attempt_record(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    client = _Client(mutation="token")
    sandbox = KataScannerSandbox(_config(tmp_path), client, journal_directory=tmp_path / "attempts")
    with pytest.raises(ValueError):
        await sandbox.run("opengrep", _spec(), Path("/opt/scanners/bin/opengrep"), source)
    records = list((tmp_path / "attempts").glob("*.json"))
    assert len(records) == 1
    record = json.loads(records[0].read_text())
    assert record["phase"] == "observation_failed"
    assert record["job_uid"] == client.uid
    assert record["execution_authority"] is False
    assert records[0].stat().st_mode & 0o077 == 0


async def test_cleanup_failure_stops_attempt_without_discarding_process_evidence(
    tmp_path: Path,
) -> None:
    from fdai.delivery.code_security_kata_sandbox import KataCleanupError

    source = tmp_path / "source"
    source.mkdir()
    client = _Client(mutation="cleanup-failed")
    sandbox = KataScannerSandbox(_config(tmp_path), client, journal_directory=tmp_path / "attempts")
    with pytest.raises(KataCleanupError) as error:
        await sandbox.run("opengrep", _spec(), Path("/opt/scanners/bin/opengrep"), source)
    assert error.value.observation is not None
    assert error.value.observation.completed
    assert sandbox.observations == (error.value.observation,)
    journal = json.loads(next((tmp_path / "attempts").glob("*.json")).read_text())
    assert journal["phase"] == "cleanup_failed"
    assert journal["process_completed"] is True and journal["exit_code"] == 0
    assert len(journal["stdout_sha256"]) == 64
    assert sum(method == "DELETE" for method, _ in client.calls) == 1


async def test_acquire_scan_and_acceptance_are_wired_without_credentials_in_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fdai.core.security.code_findings.review_signal import ReviewSource
    from fdai.delivery.code_security_acquire import AcquiredSource, GitSourceAcquirer
    from fdai.delivery.code_security_execution import run_kata_scan
    from fdai.delivery.code_security_scan_job import ScanJobConfig
    from fdai.rule_catalog.code_security import load_code_security_catalog
    from fdai.rule_catalog.code_security_scanners import ScannerCatalog
    from fdai.rule_catalog.code_security_verifiers import load_verifier_catalog

    source = tmp_path / "original"
    source.mkdir()
    (source / "app.py").write_text("print('test')\n")
    monkeypatch.setattr(
        GitSourceAcquirer,
        "acquire",
        lambda self, repository, revision: AcquiredSource(source, revision, "b" * 40),
    )
    client = _Client()
    monkeypatch.setattr(InClusterKataClient, "from_environment", lambda: client)
    catalogue_root = Path(__file__).resolve().parents[4] / "rule-catalog/code-security"
    catalog = load_code_security_catalog(catalogue_root)
    scanners = ScannerCatalog.model_validate(
        {
            "schema_version": 1,
            "catalog_id": "example.scanners",
            "version": "1.0.0",
            "scanners": {"opengrep": _spec()},
        }
    )
    result = await run_kata_scan(
        ScanJobConfig(
            repository="unused",
            revision="a" * 40,
            repository_alias="example-app",
            work_root=tmp_path / "work",
            executables={"opengrep": Path("/opt/scanners/bin/opengrep")},
            rules_dir=catalogue_root / "rules",
            source=ReviewSource(kind="git_repository", provider="git", trigger="schedule"),
        ),
        runtime=_config(tmp_path),
        catalog=catalog,
        scanners=scanners,
        verifier_catalog=load_verifier_catalog(
            catalogue_root, frozenset(catalog.weakness_classes.classes)
        ),
        acquirer=GitSourceAcquirer(tmp_path / "work"),
    )
    assert result.package["coverage_complete"] is True
    assert result.package["source"]["trigger"] == "schedule"
    assert client.deleted
    assert list((tmp_path / "work/acceptance/scans").rglob("review.json"))
    assert list((tmp_path / "work/job-attempts").glob("*.json"))
    assert "Authorization" not in json.dumps(client.job)


async def test_deadline_deletes_only_the_exact_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fdai.delivery import code_security_kata_sandbox as runtime

    source = tmp_path / "source"
    source.mkdir()
    clock = iter([0, 0, 0, 350, 350])
    monkeypatch.setattr(runtime, "time", SimpleNamespace(monotonic=lambda: next(clock)))

    async def sleep(seconds: float) -> None:
        pass

    monkeypatch.setattr(runtime.asyncio, "sleep", sleep)
    client = _Client(mutation="job-no-pod")
    result = await KataScannerSandbox(_config(tmp_path), client).run(
        "opengrep", _spec(), Path("/opt/scanners/bin/opengrep"), source
    )
    assert result.timed_out and not result.completed and client.deleted


async def test_running_scanner_uses_process_deadline_not_scheduling_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fdai.delivery import code_security_kata_sandbox as runtime

    source = tmp_path / "source"
    source.mkdir()
    clock = iter([0, 0, 0, 0, 0, 250, 250, 251, 251, 251])
    monkeypatch.setattr(runtime, "time", SimpleNamespace(monotonic=lambda: next(clock)))

    async def sleep(seconds: float) -> None:
        pass

    monkeypatch.setattr(runtime.asyncio, "sleep", sleep)
    client = _Client(mutation="quiet-running")
    spec = _spec().model_copy(update={"timeout_seconds": 600})
    result = await KataScannerSandbox(_config(tmp_path), client).run(
        "opengrep", spec, Path("/opt/scanners/bin/opengrep"), source
    )
    assert result.completed and client.deleted


async def test_a_replacement_pod_cannot_complete_the_original_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fdai.delivery import code_security_kata_sandbox as runtime

    async def sleep(seconds: float) -> None:
        pass

    monkeypatch.setattr(runtime.asyncio, "sleep", sleep)
    source = tmp_path / "source"
    source.mkdir()
    client = _Client(mutation="pod-uid-change")
    with pytest.raises(KataApiError, match="pod identity changed"):
        await KataScannerSandbox(_config(tmp_path), client).run(
            "opengrep", _spec(), Path("/opt/scanners/bin/opengrep"), source
        )
    assert client.deleted


def test_manifest_rejects_unbound_code_and_source_locations(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    for executable, root in (
        (source / "opengrep", source),
        (Path("/bin/sh"), source),
        (Path("/opt/scanners/bin/opengrep"), tmp_path.parent),
    ):
        with pytest.raises(ValueError):
            build_scanner_job(_config(tmp_path), "opengrep", _spec(), executable, root, "job")
    with pytest.raises(ValueError):
        _config(tmp_path, cache_subpath="../escape")
    with pytest.raises(ValueError):
        KataScanConfig("code-security", "example/scanner:latest", "source", tmp_path)
    rule_spec = _spec().model_copy(
        update={"mounts": ("rules",), "argv": ("scan", "{source}", "{rules}")}
    )
    with pytest.raises(ValueError, match="rule-pack handoff"):
        build_scanner_job(
            _config(tmp_path),
            "opengrep",
            rule_spec,
            Path("/opt/scanners/bin/opengrep"),
            source,
            "job",
        )
    (tmp_path / "rulepacks/digest").mkdir(parents=True)
    bound = build_scanner_job(
        _config(tmp_path, rules_subpath="rulepacks/digest"),
        "opengrep",
        rule_spec,
        Path("/opt/scanners/bin/opengrep"),
        source,
        "job",
    )
    mount = bound["spec"]["template"]["spec"]["containers"][0]["volumeMounts"]
    assert any(item.get("mountPath") == "/rules" and item["readOnly"] for item in mount)


def test_worker_runtime_requires_all_isolation_bindings_and_restricted_state() -> None:
    from fdai.delivery.code_security_cli import _parser
    from fdai.delivery.code_security_execution import kata_config

    with pytest.raises(ValueError, match="requires namespace"):
        kata_config(_parser().parse_args(["process-scheduled-scans", "--scanner-runtime", "kata"]))
    args = [
        "process-scheduled-scans",
        "--scanner-runtime",
        "kata",
        "--scanner-namespace",
        "code-security",
        "--scanner-image",
        "example/scanner@sha256:" + "a" * 64,
        "--scanner-source-pvc",
        "source",
        "--scanner-source-mount",
        "/work",
    ]
    with pytest.raises(ValueError, match="state-access restricted"):
        kata_config(_parser().parse_args(args))
    assert kata_config(_parser().parse_args([*args, "--state-access", "restricted"])) is not None


def test_rendered_runtime_does_not_share_identity_or_grant_secret_access() -> None:
    from fdai.delivery.code_security_kata_resources import scanner_runtime_resources

    resources = scanner_runtime_resources(
        "code-security", controller_namespace="core", controller_service_account="scan-controller"
    )
    items = resources["items"]
    namespace = next(item for item in items if item["kind"] == "Namespace")
    assert namespace["metadata"]["labels"]["pod-security.kubernetes.io/enforce"] == "restricted"
    for item in items:
        if item["kind"] in {"Role", "ClusterRole"}:
            for rule in item["rules"]:
                assert not set(rule["resources"]) & {"secrets", "pods/exec", "*", "nodes"}
                assert not set(rule["verbs"]) & {"*", "patch", "update", "bind", "escalate"}
        elif item["kind"].endswith("Binding"):
            assert item["subjects"][0]["namespace"] == "core"
    with pytest.raises(ValueError, match="outside the scanner namespace"):
        scanner_runtime_resources(
            "code-security",
            controller_namespace="code-security",
            controller_service_account="scan-controller",
        )


@pytest.mark.parametrize("malformed", [True, False])
async def test_lost_request_claim_is_never_reported_as_completed(malformed: bool) -> None:
    from fdai.core.security.code_findings.review_signal import ReviewSource, build_review_package
    from fdai.delivery.code_security_scan_requests import (
        ClaimedScanRequest,
        ScanOutcome,
        ScanRequest,
        ScanRequestClaimLostError,
        process_scan_requests,
    )
    from fdai.delivery.persistence.state_store_code_security_repository import register_repository
    from fdai.rule_catalog.code_security import Exposure
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    class Queue:
        async def claim(self):  # type: ignore[no-untyped-def]
            return ClaimedScanRequest(
                "key",
                "claim",
                None
                if malformed
                else ScanRequest("operator-" + "a" * 32, "example-app", None, ("Contributor",)),
            )

        async def mark_completed(self, **kwargs):  # type: ignore[no-untyped-def]
            return False

        async def mark_rejected(self, **kwargs):  # type: ignore[no-untyped-def]
            return False

    store = InMemoryStateStore()
    await register_repository(
        store, alias="example-app", location="example/app", registered_by="owner"
    )

    async def runner(repository, ref: str, source: ReviewSource):  # type: ignore[no-untyped-def]
        return ScanOutcome(
            build_review_package(
                (),
                repository_alias="example-app",
                revision="a" * 40,
                exposure=Exposure.UNKNOWN,
                coverage_complete=False,
                source=source,
            )
        )

    async def recorder(outcome: ScanOutcome) -> bool:
        return True

    with pytest.raises(ScanRequestClaimLostError):
        await process_scan_requests(Queue(), store, runner, recorder=recorder, max_requests=1)


async def test_connected_source_credential_reference_cannot_fall_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fdai.delivery.code_security_repo_cli import github_auth_header
    from fdai_github_app_auth import GitHubAppTokenError

    assert (
        await github_auth_header(
            "example/app",
            {"FDAI_GITOPS_TOKEN": "synthetic-token"},
            credential_reference="public",
        )
        is None
    )
    for environment in ({}, {"FDAI_GITOPS_TOKEN": "synthetic-token"}):
        with pytest.raises(GitHubAppTokenError):
            await github_auth_header(
                "example/app", environment, credential_reference="deployment-github-app"
            )


async def test_app_token_scope_uses_repository_name_not_owner_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import fdai_github_app_auth
    from fdai.delivery.code_security_repo_cli import github_auth_header

    requested: list[str] = []

    def provider(environment, *, http_client, repository, permissions):  # type: ignore[no-untyped-def]
        requested.append(repository)
        return None

    monkeypatch.setattr(fdai_github_app_auth, "build_github_token_provider", provider)
    assert await github_auth_header("example/app", {}) is None
    assert requested == ["app"]


async def test_api_failures_are_bounded_and_credentials_do_not_reach_scan_bindings(
    tmp_path: Path,
) -> None:
    token = tmp_path / "example-token"
    token.write_text("synthetic-test-identity")
    ca = ssl.get_default_verify_paths().cafile or "/etc/ssl/certs/ca-certificates.crt"
    assert Path(ca).is_file()
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/log"):
            return httpx.Response(200, content=b"x" * 100)
        return httpx.Response(429, json={"message": "not exposed"})

    client = InClusterKataClient(
        "https://example.invalid",
        token_file=token,
        ca_file=Path(ca),
        transport=httpx.MockTransport(handle),
    )
    try:
        with pytest.raises(KataApiError, match="HTTP 429"):
            await client.request("GET", "/test")
        assert len(calls) == 1
        assert calls[0].headers.get("Authorization") == "Bearer synthetic-test-identity"
        stdout, truncated = await client.stdout("code-security", "scanner-pod", 10)
        assert stdout == b"x" * 10 and truncated
        assert calls[-1].headers.get("Authorization") == "Bearer synthetic-test-identity"
    finally:
        await client.aclose()


def test_metadata_is_not_a_substitute_for_an_exact_owner_uid(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    job = build_scanner_job(
        _config(tmp_path), "opengrep", _spec(), Path("/opt/scanners/bin/opengrep"), source, "job"
    )
    with pytest.raises(ValueError):
        validate_scanner_pod(job, {"metadata": {"ownerReferences": []}, "spec": {}}, "expected")


def test_scanner_bootstrap_rejects_different_mounted_bytes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from fdai.delivery.code_security_cli import main
    from fdai.delivery.code_security_prepared_source import source_tree_digest

    source = tmp_path / "source"
    source.mkdir()
    file = source / "app.py"
    file.write_text("print('original')\n")
    digest = source_tree_digest(source)
    assert main(["verify-scanner-input", "--path", str(source), "--tree-digest", digest]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    file.write_text("print('different PVC input')\n")
    assert main(["verify-scanner-input", "--path", str(source), "--tree-digest", digest]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False

"""Repository registration and Console scan-request commands for ``fdai-code-security``.

``repo-register``, ``repo-list``, ``repo-enable``, and ``repo-disable`` manage which repositories
the Console may ask FDAI to scan; an Owner can make the same changes from the Console.
``process-scan-requests`` is the worker that claims pending Console requests: it applies
registration changes, then scans the registered repository at the requested ref inside the
sandbox, records the review and its issue summaries for the Console, and publishes the review
through Heimdall when a bus is bound. It is a
bounded batch job for a schedule or a one-shot run, not a polling daemon.

Repository access uses the deployment's GitHub App (``FDAI_GITHUB_APP_*``) or token
(``FDAI_GITOPS_TOKEN``) environment, narrowed to the one registered repository with read-only
contents permission. The credential reaches git only through environment configuration. Without
credentials only public repositories can be scanned.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fdai.core.security.code_findings.issue_summary import summarize_issues
from fdai.core.security.code_findings.review_signal import ReviewSource
from fdai.delivery.code_security_acquire import GitSourceAcquirer, SourceAcquisitionError
from fdai.delivery.code_security_execution import (
    add_execution_arguments,
    kata_config,
    run_kata_scan,
)
from fdai.delivery.code_security_report import (
    render_html,
    render_sarif,
    scan_report_document,
)
from fdai.delivery.code_security_review_cli import pairs
from fdai.delivery.code_security_sandbox import BubblewrapScannerSandbox
from fdai.delivery.code_security_scan_cli import default_work_root
from fdai.delivery.code_security_scan_job import ScanJobConfig, run_scan_job
from fdai.delivery.code_security_scan_requests import ScanOutcome, process_scan_requests
from fdai.delivery.code_security_scheduled_scans import (
    MAX_SCHEDULED_REPOSITORIES,
    process_scheduled_scans,
)
from fdai.delivery.code_security_worker_service import (
    WORKER_HEALTH_FILE_ENV,
    CodeSecurityWorkerServiceConfig,
    run_worker_service,
)
from fdai.delivery.persistence.state_store_code_security_repository import (
    CodeSecurityRepository,
    clone_url,
    list_repositories,
    register_repository,
    set_repository_enabled,
)
from fdai.delivery.repo_assets import repo_asset_root
from fdai.rule_catalog.code_security import Exposure, load_code_security_catalog
from fdai.rule_catalog.code_security_scanners import load_scanner_catalog
from fdai.rule_catalog.code_security_verifiers import load_verifier_catalog
from fdai.shared.providers.state_store import StateStore

_READ_ONLY_PERMISSIONS = (("contents", "read"), ("metadata", "read"))
_DEFAULT_ACTOR = "operator-cli"


def add_repository_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    register = sub.add_parser("repo-register", help="allow Console scans of a GitHub repository")
    register.add_argument("--alias", required=True)
    register.add_argument("--github", required=True, help="OWNER/REPOSITORY")
    register.add_argument(
        "--default-ref",
        default="HEAD",
        help="ref to scan by default; HEAD follows the default branch",
    )
    register.add_argument("--exposure", choices=[e.value for e in Exposure], default="unknown")
    register.add_argument("--actor", default=_DEFAULT_ACTOR, help="audited operator principal")
    sub.add_parser("repo-list", help="list repositories registered for Console scans")
    for name, text in (("repo-enable", "enable"), ("repo-disable", "disable")):
        toggle = sub.add_parser(name, help=f"{text} Console scans of a registered repository")
        toggle.add_argument("--alias", required=True)
        toggle.add_argument("--actor", default=_DEFAULT_ACTOR)
    worker = sub.add_parser(
        "process-scan-requests", help="scan pending Console requests for registered repositories"
    )
    _add_worker_arguments(worker)
    worker.add_argument("--max-requests", type=int, default=1)
    schedule = sub.add_parser(
        "process-scheduled-scans",
        help="scan every enabled registered repository at its default ref",
    )
    _add_worker_arguments(schedule)
    schedule.add_argument(
        "--max-repositories",
        type=int,
        default=5,
        help=f"scan at most this many repositories, 1 to {MAX_SCHEDULED_REPOSITORIES}",
    )
    service = sub.add_parser(
        "serve-workers",
        help="continuously invoke bounded Console-request and revision-check batches",
    )
    _add_worker_arguments(service)
    service.add_argument("--max-requests", type=int, default=20)
    service.add_argument("--max-repositories", type=int, default=5)
    service.add_argument("--request-interval-seconds", type=int, default=5)
    service.add_argument("--schedule-interval-seconds", type=int, default=300)


def _add_worker_arguments(worker: argparse.ArgumentParser) -> None:
    add_execution_arguments(worker)
    worker.add_argument(
        "--state-access",
        choices=("core", "restricted"),
        default="core",
        help="restricted uses code-security database capabilities without shared-table access",
    )
    worker.add_argument("--work-root", default=str(default_work_root()))
    worker.add_argument("--scanner-bin", action="append", default=[], help="SCANNER=EXECUTABLE")
    worker.add_argument("--required-scanner", action="append", default=[])
    worker.add_argument("--cache-dir")
    worker.add_argument("--bwrap", default="/usr/bin/bwrap")
    worker.add_argument("--kafka-bootstrap-servers")
    root = repo_asset_root() / "rule-catalog" / "code-security"
    worker.add_argument("--catalog-root", default=str(root))
    worker.add_argument("--rules-dir", default=str(root / "rules"))


def _state_store_dsn() -> str:
    dsn = (
        os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
        or os.environ.get("FDAI_DATABASE_URL", "").strip()
    )
    if not dsn:
        raise ValueError("this command requires FDAI_STATE_STORE_DSN in the environment")
    return dsn


@asynccontextmanager
async def _open_store(*, restricted: bool = False) -> AsyncIterator[StateStore]:
    from fdai.delivery.persistence.postgres import PostgresStateStore, PostgresStateStoreConfig

    store: PostgresStateStore
    if restricted:
        from fdai.delivery.persistence.postgres_code_security_state import (
            PostgresCodeSecurityStateStore,
        )

        store = PostgresCodeSecurityStateStore(
            config=PostgresStateStoreConfig(dsn=_state_store_dsn())
        )
    else:
        store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=_state_store_dsn()))
    try:
        yield store
    finally:
        await store.aclose()


def _view(repository: CodeSecurityRepository) -> dict[str, object]:
    record = repository.as_record()
    return {key: record[key] for key in record if key not in ("kind", "schema_version")}


async def run_repository_command(args: argparse.Namespace) -> dict[str, object]:
    async with _open_store() as store:
        if args.command == "repo-register":
            repository, created = await register_repository(
                store,
                alias=args.alias,
                location=args.github,
                default_ref=args.default_ref,
                exposure=Exposure(args.exposure),
                registered_by=args.actor,
            )
            return {"ok": True, "created": created, "repository": _view(repository)}
        if args.command == "repo-list":
            return {
                "ok": True,
                "repositories": [_view(item) for item in await list_repositories(store)],
            }
        repository = await set_repository_enabled(
            store, args.alias, enabled=args.command == "repo-enable", actor=args.actor
        )
        return {"ok": True, "repository": _view(repository)}


async def github_auth_header(
    location: str,
    environment: Mapping[str, str],
    *,
    credential_reference: Literal["public", "deployment-github-app"] | None = None,
) -> str | None:
    """Return a Basic authorization value for git over HTTPS, or ``None`` without credentials.

    The token is scoped to ``location`` with read-only contents permission and never leaves this
    process except through git's environment configuration.
    """
    if credential_reference == "public":
        return None
    import httpx
    from fdai_github_app_auth import (
        GitHubAppTokenError,
        GitHubAppTokenProvider,
        build_github_token_provider,
    )

    if (
        credential_reference == "deployment-github-app"
        and environment.get("FDAI_GITOPS_TOKEN", "").strip()
    ):
        raise GitHubAppTokenError("the connected source requires GitHub App credentials")

    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        provider = build_github_token_provider(
            environment,
            http_client=client,
            repository=location.rsplit("/", 1)[-1],
            permissions=_READ_ONLY_PERMISSIONS,
        )
        if credential_reference == "deployment-github-app" and not isinstance(
            provider, GitHubAppTokenProvider
        ):
            raise GitHubAppTokenError("the connected source GitHub App is unavailable")
        if provider is None:
            return None
        token = await provider()
    return "Basic " + base64.b64encode(f"x-access-token:{token}".encode()).decode("ascii")


async def _repository_source(
    args: argparse.Namespace, repository: CodeSecurityRepository
) -> tuple[GitSourceAcquirer, str]:
    from fdai_github_app_auth import GitHubAppTokenError

    try:
        header = await github_auth_header(
            repository.location,
            os.environ,
            credential_reference=(
                repository.knowledge_source.credential_reference
                if repository.knowledge_source
                else None
            ),
        )
    except GitHubAppTokenError as exc:
        raise SourceAcquisitionError("repository credentials are unavailable") from exc
    work_root = Path(args.work_root).resolve()
    acquirer = GitSourceAcquirer(work_root, auth_header=lambda: header)
    base_url = os.environ.get("FDAI_CODE_SECURITY_GITHUB_BASE_URL", "").strip()
    return acquirer, clone_url(repository, base_url or "https://github.com")


def _revision_resolver(args: argparse.Namespace):  # type: ignore[no-untyped-def]
    async def resolve(repository: CodeSecurityRepository, ref: str) -> str:
        acquirer, url = await _repository_source(args, repository)
        return await asyncio.to_thread(acquirer.resolve_revision, url, ref)

    return resolve


def _scan_runner(args: argparse.Namespace):  # type: ignore[no-untyped-def]
    runtime = kata_config(args)
    catalog_root = Path(args.catalog_root)
    catalog = load_code_security_catalog(catalog_root)
    scanners = load_scanner_catalog(catalog_root)
    verifiers = load_verifier_catalog(catalog_root, frozenset(catalog.weakness_classes.classes))
    executables = {key: Path(value).resolve() for key, value in pairs(args.scanner_bin).items()}
    unknown = set(executables) - set(scanners.scanners)
    if unknown:
        raise ValueError(f"unknown scanners: {', '.join(sorted(unknown))}")

    async def run(
        repository: CodeSecurityRepository, ref: str, source: ReviewSource
    ) -> ScanOutcome:
        acquirer, url = await _repository_source(args, repository)
        revision = await asyncio.to_thread(acquirer.resolve_revision, url, ref)
        work_root = Path(args.work_root).resolve()
        config = ScanJobConfig(
            repository=url,
            revision=revision,
            repository_alias=repository.repository_alias,
            work_root=work_root,
            executables=executables,
            rules_dir=Path(args.rules_dir).resolve(),
            cache_dir=Path(args.cache_dir).resolve() if args.cache_dir else None,
            exposure=Exposure(repository.exposure),
            required_scanners=frozenset(args.required_scanner) or None,
            source=source,
        )
        if runtime is not None:
            result = await run_kata_scan(
                config,
                runtime=runtime,
                catalog=catalog,
                scanners=scanners,
                verifier_catalog=verifiers,
                acquirer=acquirer,
            )
        else:
            result = await run_scan_job(
                config,
                catalog=catalog,
                scanners=scanners,
                acquirer=acquirer,
                sandbox=BubblewrapScannerSandbox(Path(args.bwrap)),
                verifier_catalog=verifiers,
            )
        summaries, truncated = summarize_issues(result.issues)
        generated_at = datetime.now(UTC).isoformat(timespec="seconds")
        document = scan_report_document(
            result,
            repository_alias=repository.repository_alias,
            source_label=f"{source.kind}:{source.provider}",
            generated_at=generated_at,
        )
        return ScanOutcome(
            result.package,
            summaries,
            truncated,
            {
                "html": render_html(document),
                "sarif": render_sarif(
                    result,
                    repository_alias=repository.repository_alias,
                    generated_at=generated_at,
                ),
            },
        )

    return run


def _publisher(args: argparse.Namespace):  # type: ignore[no-untyped-def]
    if not args.kafka_bootstrap_servers:
        return None
    from fdai.delivery.code_security_publish_cli import heimdall_publisher

    return heimdall_publisher(args.kafka_bootstrap_servers)


def _recorder(store: StateStore):  # type: ignore[no-untyped-def]
    from fdai.delivery.persistence.state_store_code_security_review import (
        record_code_security_review,
    )

    async def record(outcome: ScanOutcome) -> bool:
        if outcome.artifacts is None:
            raise ValueError("automatic code-security scan outcome has no report artifacts")
        created = await record_code_security_review(
            store,
            outcome.package,
            issues=outcome.issues,
            issues_truncated=outcome.issues_truncated,
            artifacts=outcome.artifacts,
        )
        return created

    return record


async def run_process_scan_requests(args: argparse.Namespace) -> dict[str, object]:
    from fdai.delivery.persistence.postgres_code_security_scan_requests import (
        PostgresCodeSecurityScanRequestQueue,
        PostgresCodeSecurityScanRequestQueueConfig,
    )

    runner = _scan_runner(args)
    publisher = _publisher(args)
    queue = PostgresCodeSecurityScanRequestQueue(
        PostgresCodeSecurityScanRequestQueueConfig(
            dsn=_state_store_dsn(),
            worker_id=f"code-security-worker-{uuid4().hex}",
            lease_seconds=60,
            restricted_access=args.state_access == "restricted",
        )
    )
    async with _open_store(restricted=args.state_access == "restricted") as store:
        outcomes = await process_scan_requests(
            queue,
            store,
            runner,
            recorder=_recorder(store),
            publisher=publisher,
            max_requests=args.max_requests,
        )
    return {"ok": True, "processed": len(outcomes), "outcomes": list(outcomes)}


async def run_process_scheduled_scans(args: argparse.Namespace) -> dict[str, object]:
    runner = _scan_runner(args)
    publisher = _publisher(args)
    async with _open_store(restricted=args.state_access == "restricted") as store:
        outcomes = await process_scheduled_scans(
            store,
            runner,
            resolver=_revision_resolver(args),
            recorder=_recorder(store),
            publisher=publisher,
            max_repositories=args.max_repositories,
        )
    scanned = [item for item in outcomes if item["status"] != "deferred"]
    return {
        "ok": all(item["status"] in {"published", "unchanged"} for item in scanned),
        "checked": len(scanned),
        "scanned": sum(item["status"] == "published" for item in scanned),
        "unchanged": sum(item["status"] == "unchanged" for item in scanned),
        "deferred": sum(item["status"] == "deferred" for item in outcomes),
        "outcomes": list(outcomes),
    }


async def run_worker_service_command(args: argparse.Namespace) -> None:
    from fdai.delivery.persistence.postgres_code_security_scan_requests import (
        PostgresCodeSecurityScanRequestQueue,
        PostgresCodeSecurityScanRequestQueueConfig,
    )

    runner = _scan_runner(args)
    resolver = _revision_resolver(args)
    publisher = _publisher(args)
    queue = PostgresCodeSecurityScanRequestQueue(
        PostgresCodeSecurityScanRequestQueueConfig(
            dsn=_state_store_dsn(),
            worker_id=f"code-security-worker-{uuid4().hex}",
            lease_seconds=60,
            restricted_access=args.state_access == "restricted",
        )
    )
    health_file = os.environ.get(WORKER_HEALTH_FILE_ENV, "").strip()
    config = CodeSecurityWorkerServiceConfig(
        request_interval_seconds=args.request_interval_seconds,
        schedule_interval_seconds=args.schedule_interval_seconds,
        health_file=Path(health_file) if health_file else None,
    )
    async with _open_store(restricted=args.state_access == "restricted") as store:
        recorder = _recorder(store)

        async def request_batch() -> list[dict[str, object]]:
            return list(
                await process_scan_requests(
                    queue,
                    store,
                    runner,
                    recorder=recorder,
                    publisher=publisher,
                    max_requests=args.max_requests,
                )
            )

        async def schedule_batch() -> list[dict[str, object]]:
            return list(
                await process_scheduled_scans(
                    store,
                    runner,
                    resolver=resolver,
                    recorder=recorder,
                    publisher=publisher,
                    max_repositories=args.max_repositories,
                )
            )

        await run_worker_service(
            store,
            request_batch=request_batch,
            schedule_batch=schedule_batch,
            config=config,
        )


__all__ = [
    "add_repository_commands",
    "github_auth_header",
    "run_process_scan_requests",
    "run_process_scheduled_scans",
    "run_repository_command",
    "run_worker_service_command",
]

"""``publish-review`` command: route a scan's review package through Heimdall.

The command ingests SARIF, builds canonical issues and a coverage receipt, and produces the strict
no-authority review package. With ``--kafka-bootstrap-servers`` it publishes the package through
Heimdall's ``object.drift`` ownership on the deployment event bus, where Forseti judges it and
Saga audits the verdict. Without a bus it writes the package for a later governed publisher.
Either way it plans A2 and A4 notifications against the deployment's notification matrix. When
the governed matrix lacks the code-security routes, the review is still published and recorded,
and the output names the missing routes as a notification gap. Nothing falls back to the approval
channel.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path

from fdai.core.notifications.matrix import load_matrix_from_yaml
from fdai.core.security.code_findings import (
    AnalysisContext,
    Lane,
    SarifIngestContext,
    build_issues,
    ingest_sarif,
)
from fdai.core.security.code_findings.notify import (
    NotificationPlanError,
    plan_code_security_notifications,
)
from fdai.core.security.code_findings.receipts import build_receipt
from fdai.core.security.code_findings.review_signal import (
    SOURCE_KINDS,
    ReviewSource,
    build_review_package,
    code_security_drift_payload,
)
from fdai.core.security.code_findings.verification import ScanCoverageReceipt
from fdai.delivery.repo_assets import repo_asset_root
from fdai.rule_catalog.code_security import Exposure, load_code_security_catalog
from fdai.shared.providers.notifications.base import NotificationMessage


def add_publish_command(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    publish = sub.add_parser("publish-review", help="publish a scan review through Heimdall")
    publish.add_argument("--sarif", action="append", required=True, help="FILE:LANE")
    publish.add_argument("--revision", required=True)
    publish.add_argument("--repo-alias", required=True)
    publish.add_argument("--exposure", choices=[e.value for e in Exposure], default="unknown")
    publish.add_argument("--known-exploited", help="file with one advisory id per line")
    publish.add_argument("--source-root", action="append", default=[])
    publish.add_argument("--full-repository", action="append", default=[], help="PRODUCER")
    publish.add_argument("--out", help="write the review package and planned notifications here")
    publish.add_argument(
        "--source-kind",
        choices=list(SOURCE_KINDS),
        help="where the SARIF came from; defaults to external_sarif when any lane is external",
    )
    publish.add_argument(
        "--source-provider",
        default="sarif",
        help="short provider token shown in the Console, such as mdash or github-code-scanning",
    )
    publish.add_argument("--kafka-bootstrap-servers", help="publish on the deployment event bus")
    publish.add_argument(
        "--record-state",
        action="store_true",
        help="record the review for the Console in the state store from FDAI_STATE_STORE_DSN",
    )
    publish.add_argument(
        "--matrix", default=str(repo_asset_root() / "config" / "notifications-matrix.yaml")
    )
    publish.add_argument(
        "--catalog-root", default=str(repo_asset_root() / "rule-catalog" / "code-security")
    )


def coverage_complete(receipt: ScanCoverageReceipt) -> bool:
    """True only when every producer reported completion without truncation."""
    return bool(receipt.runs) and all(
        run.completed is True and not run.truncated for run in receipt.runs
    )


class _BusHeimdallPublisher:
    """Publish one review through Heimdall on the deployment event bus, then close the bus."""

    def __init__(self, bootstrap_servers: str) -> None:
        self._bootstrap_servers = bootstrap_servers

    async def publish_code_security_drift(self, package: Mapping[str, object]) -> bool:
        import httpx

        from fdai.agents import EventBusBridge, load_pantheon
        from fdai.agents.heimdall import Heimdall
        from fdai.delivery.azure.event_bus import EventHubsKafkaBus, EventHubsKafkaBusConfig
        from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=15.0, write=15.0, pool=5.0)
        ) as http_client:
            bus = EventHubsKafkaBus(
                identity=ManagedIdentityWorkloadIdentity.from_env(http_client=http_client),
                config=EventHubsKafkaBusConfig(
                    bootstrap_servers=self._bootstrap_servers,
                    client_id="fdai-code-security-review",
                ),
            )
            try:
                heimdall = Heimdall(
                    bus=EventBusBridge(provider=bus, registry=load_pantheon()),
                    code_security_drift_projector=code_security_drift_payload,
                )
                return await heimdall.publish_code_security_drift(package)
            finally:
                await bus.close()


def heimdall_publisher(bootstrap_servers: str) -> _BusHeimdallPublisher:
    """Return a publisher that routes reviews through Heimdall on the deployment bus."""
    return _BusHeimdallPublisher(bootstrap_servers)


def build_review(
    args: argparse.Namespace,
) -> tuple[dict[str, object], tuple[NotificationMessage, ...], str | None]:
    catalog = load_code_security_catalog(Path(args.catalog_root))
    ingested = []
    for spec in args.sarif:
        file_name, _, lane = spec.rpartition(":")
        ingested.append(
            ingest_sarif(
                Path(file_name).read_bytes(),
                SarifIngestContext(
                    lane=Lane(lane), revision=args.revision, source_roots=tuple(args.source_root)
                ),
            )
        )
    known = frozenset(
        line.strip()
        for line in (
            Path(args.known_exploited).read_text().splitlines() if args.known_exploited else []
        )
        if line.strip()
    )
    issues = build_issues(
        [occ for result in ingested for occ in result.occurrences],
        catalog,
        AnalysisContext(
            revision=args.revision, exposure=Exposure(args.exposure), known_exploited=known
        ),
    )
    receipt = build_receipt(
        args.revision,
        catalog.version_stamp(),
        ingested,
        full_repository=frozenset(args.full_repository),
    )
    lanes = {spec.rpartition(":")[2] for spec in args.sarif}
    kind = args.source_kind or (
        "external_sarif" if Lane.EXTERNAL.value in lanes else "git_repository"
    )
    package = build_review_package(
        issues,
        repository_alias=args.repo_alias,
        revision=args.revision,
        exposure=Exposure(args.exposure),
        coverage_complete=coverage_complete(receipt),
        source=ReviewSource(kind=kind, provider=args.source_provider, trigger="cli"),
        producers=sorted({run.producer for run in receipt.runs}),
    )
    routes = load_matrix_from_yaml(Path(args.matrix)).routes
    try:
        return package, plan_code_security_notifications(package, routes=set(routes)), None
    except NotificationPlanError as exc:
        return package, (), str(exc)


async def publish_review(args: argparse.Namespace) -> dict[str, object]:
    package, messages, notification_gap = build_review(args)
    planned = [
        {
            "category": message.category,
            "trust_tier": message.trust_tier.value,
            "template_key": message.template_key,
            "correlation_id": message.correlation_id,
        }
        for message in messages
    ]
    published = False
    if args.kafka_bootstrap_servers:
        published = await heimdall_publisher(
            args.kafka_bootstrap_servers
        ).publish_code_security_drift(package)
    recorded = False
    if args.record_state:
        from fdai.delivery.persistence.state_store_code_security_review import (
            record_review_from_environment,
        )

        recorded = await record_review_from_environment(package)
    if args.out:
        Path(args.out).write_text(
            json.dumps({"package": package, "notifications": planned}, indent=2) + "\n"
        )
    return {
        "ok": True,
        "published": published,
        "recorded": recorded,
        "decision": code_security_drift_payload(package)["decision"],
        "issue_count": package["issue_count"],
        "notifications": planned,
        "notification_gap": notification_gap,
    }


__all__ = [
    "add_publish_command",
    "build_review",
    "coverage_complete",
    "heimdall_publisher",
    "publish_review",
]

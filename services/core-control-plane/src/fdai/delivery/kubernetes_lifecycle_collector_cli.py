"""One-shot batch entry point for durable Kubernetes lifecycle collection.

This binds the same server-owned Kubernetes credential env vars as
`fdai.runtime.resource_event_providers` (`FDAI_KUBERNETES_*`) to run exactly one
bounded list-or-watch poll against the configured cluster and durably append any
new lifecycle observations behind the atomic Postgres cursor store. It is an
injectable execution seam: no Container Apps Job/Terraform schedule invokes it yet,
so recurring collection is not wired end to end until that scheduling gap is closed
(see `docs/roadmap/architecture/continuous-operational-instance-graph.md`).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Sequence

import httpx
import psycopg

from fdai.delivery.kubernetes_lifecycle_collector import collect_kubernetes_lifecycle_once
from fdai.delivery.persistence.postgres_kubernetes_lifecycle import (
    PostgresKubernetesLifecycleStore,
    PostgresKubernetesLifecycleStoreConfig,
)
from fdai.runtime.resource_event_providers import build_kubernetes_lifecycle_source
from fdai.runtime.venue import resolve_execution_venue, uses_developer_identity


async def _identity(http_client: httpx.AsyncClient) -> object | None:
    """Resolve the workload identity used only for `workload-identity` auth mode.

    Returns `None` when the configured auth mode does not require one (for example
    `service-account`), matching `build_kubernetes_lifecycle_source`'s own contract.
    """

    if os.environ.get("FDAI_KUBERNETES_AUTH_MODE", "").strip() != "workload-identity":
        return None
    if uses_developer_identity(resolve_execution_venue()):
        from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity

        return AsyncAzureCliWorkloadIdentity.from_env()
    from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity

    return ManagedIdentityWorkloadIdentity.from_env(http_client=http_client)


async def _run(*, cluster_ref: str) -> dict[str, object]:
    dsn = os.environ.get("FDAI_DATABASE_URL", "").strip()
    if not dsn:
        raise ValueError("FDAI_DATABASE_URL MUST be configured")
    async with httpx.AsyncClient() as http_client:
        identity = await _identity(http_client)
        source = build_kubernetes_lifecycle_source(environment=os.environ, identity=identity)
        if source is None:
            raise ValueError("FDAI_KUBERNETES_* Kubernetes lifecycle binding is unconfigured")
        store = PostgresKubernetesLifecycleStore(
            config=PostgresKubernetesLifecycleStoreConfig(dsn=dsn)
        )
        receipt = await collect_kubernetes_lifecycle_once(
            source=source, store=store, cluster_ref=cluster_ref
        )
    return {
        "cluster_ref": receipt.cluster_ref,
        "polled_count": receipt.polled_count,
        "inserted_count": receipt.inserted_count,
        "duplicate_count": receipt.duplicate_count,
        "cursor": receipt.cursor,
        "complete": receipt.complete,
        "limitation": receipt.limitation,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run exactly one bounded Kubernetes lifecycle collection pass.

    `cluster_ref` is sourced solely from `FDAI_KUBERNETES_CLUSTER_REF`: the source
    built by `build_kubernetes_lifecycle_source` always binds its own `cluster_ref`
    from that same environment variable, so an independent positional override
    here could never be honored by the real source (it would either be a silent
    no-op when it matched, or a guaranteed `ValueError` crash when it did not).
    Any positional argument is therefore rejected explicitly rather than accepted
    and then silently ignored or left to crash deep inside `poll()`.
    """

    arguments = list(argv if argv is not None else sys.argv[1:])
    if arguments:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": (
                        "positional arguments are not supported; set "
                        "FDAI_KUBERNETES_CLUSTER_REF instead"
                    ),
                },
                sort_keys=True,
            )
        )
        return 2
    cluster_ref = os.environ.get("FDAI_KUBERNETES_CLUSTER_REF", "").strip()
    if not cluster_ref:
        print(json.dumps({"status": "failed", "reason": "cluster_ref is required"}, sort_keys=True))
        return 2
    try:
        summary = asyncio.run(_run(cluster_ref=cluster_ref))
    except psycopg.Error as exc:
        print(
            json.dumps(
                {"status": "failed", "reason": f"database_{type(exc).__name__}"},
                sort_keys=True,
            )
        )
        return 3
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"status": "completed", **summary}, sort_keys=True))
    return 0 if summary["complete"] else 1


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    raise SystemExit(main())


__all__ = ["main"]

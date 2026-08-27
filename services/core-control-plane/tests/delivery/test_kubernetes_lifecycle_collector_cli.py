"""Batch-entrypoint tests for the Kubernetes lifecycle collector CLI seam."""

from __future__ import annotations

import json

import httpx
from fdai.delivery import kubernetes_lifecycle_collector_cli as cli
from fdai.delivery.kubernetes_lifecycle_collector import KubernetesLifecycleCollectionReceipt


def _receipt(
    *, complete: bool = True, limitation: str | None = None
) -> KubernetesLifecycleCollectionReceipt:
    return KubernetesLifecycleCollectionReceipt(
        cluster_ref="cluster-a",
        polled_count=1,
        inserted_count=1,
        duplicate_count=0,
        complete=complete,
        limitation=limitation,
        cursor="1000" if complete else None,
    )


def test_missing_database_url_fails_with_an_explicit_reason(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("FDAI_DATABASE_URL", raising=False)
    monkeypatch.setenv("FDAI_KUBERNETES_CLUSTER_REF", "cluster-a")

    exit_code = cli.main([])

    assert exit_code == 2
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "failed"
    assert "FDAI_DATABASE_URL" in printed["reason"]


def test_missing_cluster_ref_fails_with_an_explicit_reason(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("FDAI_DATABASE_URL", "postgresql://example/db")
    monkeypatch.delenv("FDAI_KUBERNETES_CLUSTER_REF", raising=False)

    exit_code = cli.main([])

    assert exit_code == 2
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "failed"
    assert "cluster_ref" in printed["reason"]


def test_unconfigured_kubernetes_binding_fails_with_an_explicit_reason(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("FDAI_DATABASE_URL", "postgresql://example/db")
    monkeypatch.setenv("FDAI_KUBERNETES_CLUSTER_REF", "cluster-a")
    monkeypatch.delenv("FDAI_KUBERNETES_API_SERVER", raising=False)
    monkeypatch.setattr(cli, "build_kubernetes_lifecycle_source", lambda **_: None)

    exit_code = cli.main([])

    assert exit_code == 2
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "failed"
    assert "unconfigured" in printed["reason"]


def test_successful_complete_collection_reports_the_receipt(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("FDAI_DATABASE_URL", "postgresql://example/db")
    monkeypatch.setenv("FDAI_KUBERNETES_CLUSTER_REF", "cluster-a")
    monkeypatch.setattr(cli, "build_kubernetes_lifecycle_source", lambda **_: object())
    monkeypatch.setattr(cli, "PostgresKubernetesLifecycleStore", lambda **_: object())

    async def _fake_collect(*, source, store, cluster_ref):  # type: ignore[no-untyped-def]
        assert cluster_ref == "cluster-a"
        return _receipt(complete=True)

    monkeypatch.setattr(cli, "collect_kubernetes_lifecycle_once", _fake_collect)

    exit_code = cli.main([])

    assert exit_code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "completed"
    assert printed["cluster_ref"] == "cluster-a"
    assert printed["inserted_count"] == 1
    assert printed["complete"] is True
    assert printed["limitation"] is None


def test_incomplete_collection_reports_the_gap_and_a_nonzero_exit_code(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("FDAI_DATABASE_URL", "postgresql://example/db")
    monkeypatch.setenv("FDAI_KUBERNETES_CLUSTER_REF", "cluster-a")
    monkeypatch.setattr(cli, "build_kubernetes_lifecycle_source", lambda **_: object())
    monkeypatch.setattr(cli, "PostgresKubernetesLifecycleStore", lambda **_: object())

    async def _fake_collect(*, source, store, cluster_ref):  # type: ignore[no-untyped-def]
        return _receipt(complete=False, limitation="source_unavailable")

    monkeypatch.setattr(cli, "collect_kubernetes_lifecycle_once", _fake_collect)

    exit_code = cli.main([])

    assert exit_code == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "completed"
    assert printed["complete"] is False
    assert printed["limitation"] == "source_unavailable"


def test_positional_cluster_ref_argument_overrides_the_environment(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("FDAI_DATABASE_URL", "postgresql://example/db")
    monkeypatch.setenv("FDAI_KUBERNETES_CLUSTER_REF", "cluster-env")
    monkeypatch.setattr(cli, "build_kubernetes_lifecycle_source", lambda **_: object())
    monkeypatch.setattr(cli, "PostgresKubernetesLifecycleStore", lambda **_: object())
    seen: list[str] = []

    async def _fake_collect(*, source, store, cluster_ref):  # type: ignore[no-untyped-def]
        seen.append(cluster_ref)
        return _receipt(complete=True)

    monkeypatch.setattr(cli, "collect_kubernetes_lifecycle_once", _fake_collect)

    exit_code = cli.main(["cluster-argument"])

    assert exit_code == 0
    assert seen == ["cluster-argument"]


async def test_identity_stays_none_outside_workload_identity_auth_mode(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("FDAI_KUBERNETES_AUTH_MODE", raising=False)
    async with httpx.AsyncClient() as http_client:
        identity = await cli._identity(http_client)

    assert identity is None


async def test_identity_stays_none_for_service_account_auth_mode(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("FDAI_KUBERNETES_AUTH_MODE", "service-account")
    async with httpx.AsyncClient() as http_client:
        identity = await cli._identity(http_client)

    assert identity is None

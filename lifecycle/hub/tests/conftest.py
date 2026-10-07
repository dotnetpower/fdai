from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime, time, timedelta
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.runtime_release import RuntimeRelease, parse_runtime_release_manifest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from fdai_lifecycle_hub.catalog import ReleaseCatalog
from fdai_lifecycle_hub.domain import (
    Configuration,
    DailyWindow,
    Entity,
    EntityState,
    Health,
    Installation,
    Planner,
    ReportedState,
    Settings,
)
from fdai_lifecycle_hub.planning import plan_next
from fdai_lifecycle_hub.signing import HubSigningKey
from fdai_lifecycle_hub.store import HubStore

# 12:00 in Asia/Seoul, inside the fixture's 11:30-12:30 daily window.
NOW = datetime(2026, 10, 5, 3, tzinfo=UTC)
IMAGE_DIGEST = "sha256:" + "b" * 64
SERVICES = (
    "core-control-plane",
    "operator-service",
    "document-ingestion-api",
    "document-processing-worker",
    "isolated-executor",
)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _artifact(role: str, *kinds: str, image: bool = False) -> dict[str, str]:
    record = {kind: f"runtime/{role}/{kind}.bin" for kind in kinds}
    record |= {f"{kind}_sha256": _digest(f"{role}-{kind}") for kind in kinds}
    if image:
        record["image_digest"] = IMAGE_DIGEST
    return record


def _manifest(release_id: str) -> dict[str, Any]:
    """A minimal valid fdai.runtime-release.v3 manifest. Artifacts are not read."""

    service = ("archive", "sbom", "provenance")
    return {
        "schema_version": "fdai.runtime-release.v3",
        "source_commit": "a" * 40,
        "platform_tag": "linux-x86_64",
        "deployment_bundle_sha256": _digest(f"bundle-{release_id}"),
        "services": {role: _artifact(role, *service, image=True) for role in SERVICES},
        "sidecars": {
            role: _artifact(role, *service, image=True) for role in ("clamav", "pgvector")
        },
        "installation_agents": {
            role: _artifact(role, *service, image=True)
            for role in ("infrastructure-agent", "lifecycle-agent")
        },
        "console": _artifact("console", "archive", "sbom"),
        "deployment_support": _artifact("deployment-support", "archive", "sbom"),
        "schema": {"target": 15, "tolerates": {"minimum": 12, "maximum": 16}},
        "capabilities": {"action:scale-service": {"kind": "ActionType", "maximum_mode": "enforce"}},
        "downtime": {"entities": []},
    }


def _release(release_id: str) -> RuntimeRelease:
    return parse_runtime_release_manifest(canonical_bytes(_manifest(release_id)))


RELEASE_IDS = ("1.4.0", "1.5.0", "1.6.0")


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def catalog() -> ReleaseCatalog:
    ids = RELEASE_IDS
    return ReleaseCatalog(
        releases={release_id: _release(release_id) for release_id in ids},
        channels={"stable": frozenset(ids)},
    )


@pytest.fixture
def installation() -> Installation:
    return Installation(
        installation_id="installation-alpha",
        settings=Settings(
            channel="stable",
            version_range=">=1.4.0 <2.0.0",
            region="korea-central",
            allowed_regions=frozenset({"korea-central"}),
            windows=(DailyWindow(time(11, 30), timedelta(hours=1), "Asia/Seoul"),),
        ),
        entities=frozenset(
            {
                Entity(entity_id="core", kind="service", managed=True),
                Entity(entity_id="console", kind="static-site", managed=False),
            }
        ),
        configuration=Configuration(
            schema={
                "replicas": {
                    "default": 1,
                    "x-fdai-axis": "Release channel subscription",
                    "x-fdai-owner": "customer",
                }
            },
            environment={},
            entity_overrides=({"versions": ">=1.0.0 <2.0.0", "values": {"replicas": 2}},),
        ),
        reported=ReportedState(
            digest=_digest("reported-state"),
            schema_revision=15,
            entities={
                "core": EntityState(
                    release_id="1.4.0",
                    artifact_digests=frozenset({IMAGE_DIGEST}),
                    health=Health.HEALTHY,
                ),
                "console": EntityState(
                    release_id="1.4.0", artifact_digests=frozenset(), health=Health.HEALTHY
                ),
            },
            observed_at=NOW - timedelta(minutes=1),
        ),
    )


@pytest.fixture
def key() -> HubSigningKey:
    return HubSigningKey(Ed25519PrivateKey.generate(), epoch=1)


@pytest.fixture
def planner(catalog: ReleaseCatalog, key: HubSigningKey) -> Planner:
    return partial(plan_next, catalog=catalog, key=key)


@pytest.fixture
def store() -> Iterator[HubStore]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    hub_store = HubStore(engine)
    hub_store.create_schema()
    yield hub_store
    engine.dispose()


@pytest.fixture
def catalog_dir(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    (root / "releases").mkdir(parents=True)
    for release_id in RELEASE_IDS:
        (root / "releases" / f"{release_id}.json").write_bytes(
            canonical_bytes(_manifest(release_id))
        )
    (root / "channels.json").write_text(json.dumps({"stable": list(RELEASE_IDS)}))
    return root

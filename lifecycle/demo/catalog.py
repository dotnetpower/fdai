"""Generate the demo's Release catalog, signed agent inputs, and Hub input files.

Releases 1.0.0 and 1.1.0 pin two public `nginx-unprivileged` image indexes by digest. Release 1.2.0
names a digest that no registry holds, so applying it fails its health check and the agent rolls
back. Every image-bearing component of a Release uses the Release's one image.

The Hub plans a Release only when the installation reports every image it needs as available, and
it reads availability from the artifact digests of all reported Entities. `core` reports only the
image it runs, so an unmanaged `artifact-mirror` Entity reports the three demo images. The agent
carries Entities outside its Plan unchanged into each new snapshot. Keys are generated into the
work directory and never committed.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.runtime_release import parse_runtime_release_manifest

from fdai_lifecycle_agent.cli import LOCAL_POLICY_SCHEMA
from fdai_lifecycle_hub.signing import generate_development_key, load_private_key

INSTALLATION_ID = "demo"
CHANNEL = "demo"
ENTITY = "core"
MIRROR = "artifact-mirror"
COMPONENT = "core-control-plane"
REGION = "demo"
INITIAL_RELEASE = "0.0.0"
IMAGE_REPOSITORY = "docker.io/nginxinc/nginx-unprivileged"
CAPABILITY = "action:scale-service"
SCHEMA_REVISION = 15
KEYS = ("hub", "installation", "release", "configuration")
MARKER = ".fdai-lifecycle-demo"


@dataclass(frozen=True, slots=True)
class DemoRelease:
    release_id: str
    image_digest: str
    image: str


def _hex(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


RELEASES = (
    DemoRelease(
        "1.0.0",
        "sha256:65e3e85dbaed8ba248841d9d58a899b6197106c23cb0ff1a132b7bfe0547e4c0",
        "nginx-unprivileged 1.27.5-alpine",
    ),
    DemoRelease(
        "1.1.0",
        "sha256:c97ff0bf7cbae369953c6da1232ec14ad9f971d66360c5698db0856a4cd657a0",
        "nginx-unprivileged 1.28.0-alpine",
    ),
    DemoRelease("1.2.0", f"sha256:{_hex('fdai-lifecycle-demo-broken-1.2.0')}", "missing digest"),
)
RELEASES_BY_ID = {release.release_id: release for release in RELEASES}

_SECTIONS = {
    "services": (
        "core-control-plane",
        "operator-service",
        "document-ingestion-api",
        "document-processing-worker",
        "isolated-executor",
    ),
    "sidecars": ("clamav", "pgvector"),
    "installation_agents": ("infrastructure-agent", "lifecycle-agent"),
}
# Covers 0.0.0, so `manage` accepts the Entity before its first Release.
_OVERRIDES = [{"versions": ">=0.0.0 <2.0.0", "values": {"replicas": 1}}]
CONFIGURATION: dict[str, Any] = {
    "schema": {
        "replicas": {
            "default": 1,
            "x-fdai-axis": "Release channel subscription",
            "x-fdai-owner": "customer",
        }
    },
    "environment": {},
    "entity_overrides": _OVERRIDES,
}


@dataclass(frozen=True, slots=True)
class Layout:
    """Where the demo keeps its files under one work directory."""

    root: Path

    def key(self, name: str) -> Path:
        return self.root / "keys" / f"{name}.pem"

    def public_key(self, name: str) -> Path:
        return self.root / "keys" / f"{name}.pub.pem"

    @property
    def catalog(self) -> Path:
        return self.root / "catalog"

    @property
    def channels(self) -> Path:
        return self.catalog / "channels.json"

    @property
    def inputs(self) -> Path:
        return self.root / "inputs"

    @property
    def agent_state(self) -> Path:
        return self.root / "agent-state"

    @property
    def enrollment(self) -> Path:
        return self.root / "enrollment.json"

    @property
    def ownership(self) -> Path:
        return self.root / "ownership.json"

    @property
    def settings(self) -> Path:
        return self.root / "core-settings.json"

    @property
    def current_state(self) -> Path:
        return self.root / "current-state.json"

    @property
    def local_policy(self) -> Path:
        return self.root / "local-policy.json"

    @property
    def database_url(self) -> str:
        return f"sqlite+pysqlite:///{self.root / 'hub.db'}"


def manifest(release: DemoRelease) -> dict[str, Any]:
    """A valid fdai.runtime-release.v3 manifest. The Hub and agent never read its archives."""

    def artifact(role: str, *kinds: str, image: bool) -> dict[str, str]:
        record = {kind: f"runtime/{role}/{kind}.bin" for kind in kinds}
        record |= {f"{kind}_sha256": _hex(f"{release.release_id}-{role}-{kind}") for kind in kinds}
        return record | ({"image_digest": release.image_digest} if image else {})

    image_kinds = ("archive", "sbom", "provenance")
    document: dict[str, Any] = {
        "schema_version": "fdai.runtime-release.v3",
        "source_commit": _hex(f"commit-{release.release_id}")[:40],
        "platform_tag": "linux-x86_64",
        "deployment_bundle_sha256": _hex(f"bundle-{release.release_id}"),
    }
    for section, roles in _SECTIONS.items():
        document[section] = {role: artifact(role, *image_kinds, image=True) for role in roles}
    return document | {
        "console": artifact("console", "archive", "sbom", image=False),
        "deployment_support": artifact("deployment-support", "archive", "sbom", image=False),
        "schema": {"target": SCHEMA_REVISION, "tolerates": {"minimum": 12, "maximum": 16}},
        "capabilities": {CAPABILITY: {"kind": "ActionType", "maximum_mode": "enforce"}},
        "downtime": {"entities": []},
    }


def state_snapshot(
    release_id: str, running: list[str], health: str, observed_at: datetime
) -> dict[str, Any]:
    """A snapshot in the agent's form: the digest is the canonical SHA-256 of everything else."""

    def entity(release: str, digests: list[str], status: str) -> dict[str, Any]:
        return {"release_id": release, "artifact_digests": sorted(digests), "health": status}

    available = [release.image_digest for release in RELEASES]
    content = {
        "schema_revision": SCHEMA_REVISION,
        "entities": {
            ENTITY: entity(release_id, running, health),
            MIRROR: entity(INITIAL_RELEASE, available, "healthy"),
        },
        "observed_at": observed_at.astimezone(UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
    }
    return {"digest": canonical_digest(content), **content}


def enrollment(observed_at: datetime) -> dict[str, Any]:
    """The enrollment request before `dev-enroll` adds the installation key and time."""

    # Two overlapping daily windows, so one always has more than the Plan's 30 minutes left.
    windows = [
        {"start": start, "duration": "P1D", "timezone": "UTC"} for start in ("00:00:00", "12:00:00")
    ]
    return {
        "installation_id": INSTALLATION_ID,
        "settings": {
            "channel": CHANNEL,
            "version_range": ">=1.0.0 <2.0.0",
            "region": REGION,
            "allowed_regions": [REGION],
            "windows": windows,
        },
        "entities": [
            {"entity_id": ENTITY, "kind": "service"},
            {"entity_id": MIRROR, "kind": "artifact-store"},
        ],
        "configuration": CONFIGURATION,
        "reported": state_snapshot(INITIAL_RELEASE, [], "unknown", observed_at),
    }


def local_policy(*, apply: bool) -> dict[str, Any]:
    """The agent's local hard limit. `component_images` exists only in apply mode."""

    policy: dict[str, Any] = {
        "schema": LOCAL_POLICY_SCHEMA,
        "entity_ids": [ENTITY],
        "regions": [REGION],
        "capability_modes": {CAPABILITY: "enforce"},
        "destructive_allowed": False,
        "max_duration_minutes": 60,
        "entity_components": {ENTITY: [COMPONENT]},
    }
    if apply:
        policy["component_images"] = {COMPONENT: IMAGE_REPOSITORY}
    return policy


def reset(root: Path) -> None:
    """Remove an earlier demo work directory. Refuses one the demo didn't create, even if empty."""

    if not root.exists():
        return
    if not (root / MARKER).is_file():
        raise ValueError(f"{root} exists and wasn't created by the demo")
    shutil.rmtree(root)


def prepare(layout: Layout, *, now: datetime | None = None) -> None:
    """Write keys, the catalog with an empty channel, signed agent inputs, and Hub inputs."""

    layout.root.mkdir(parents=True, exist_ok=True)
    (layout.root / MARKER).touch()
    (layout.root / "keys").mkdir()
    for name in KEYS:
        generate_development_key(layout.key(name))

    (layout.catalog / "releases").mkdir(parents=True)
    for release in RELEASES:
        payload = canonical_bytes(manifest(release))
        (layout.catalog / "releases" / f"{release.release_id}.json").write_bytes(payload)
        digest = parse_runtime_release_manifest(payload).digest
        _write_signed(layout, "releases", digest, payload, key="release")
    _write_json(layout.channels, {CHANNEL: []})
    _write_signed(
        layout,
        "configurations",
        canonical_digest(CONFIGURATION),
        canonical_bytes(CONFIGURATION),
        key="configuration",
    )

    request = enrollment(now or datetime.now(UTC))
    _write_json(layout.enrollment, request)
    _write_json(layout.current_state, request["reported"])
    _write_json(
        layout.ownership,
        {
            "foundation_receipt_digest": f"sha256:{_hex('demo-foundation-receipt')}",
            "terraform_state_digest": f"sha256:{_hex('demo-terraform-state')}",
            "managed_tag": True,
        },
    )
    _write_json(layout.settings, {"overrides": _OVERRIDES})


def publish(layout: Layout, release_id: str) -> list[str]:
    """Add one demo Release to the channel and return the channel's Releases."""

    if release_id not in RELEASES_BY_ID:
        raise ValueError(f"not a demo Release: {release_id} (choose from {sorted(RELEASES_BY_ID)})")
    channels: dict[str, list[str]] = json.loads(layout.channels.read_bytes())
    members = sorted({*channels[CHANNEL], release_id})
    _write_json(layout.channels, {CHANNEL: members})
    return members


def _write_signed(layout: Layout, kind: str, digest: str, payload: bytes, *, key: str) -> None:
    directory = layout.inputs / kind
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{digest}.json").write_bytes(payload)
    (directory / f"{digest}.sig").write_bytes(load_private_key(layout.key(key)).sign(payload))


def _write_json(path: Path, document: object) -> None:
    path.write_text(json.dumps(document, indent=2) + "\n")

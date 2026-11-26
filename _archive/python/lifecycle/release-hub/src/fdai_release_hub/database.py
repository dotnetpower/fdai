"""Portable publication tables, including a singleton catalog lock shared by all replicas."""

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

metadata = MetaData()
releases = Table(
    "releases",
    metadata,
    Column("id", String(160), primary_key=True),
    Column("label", Text, nullable=False),
    Column("manifest", Text, nullable=False),
    Column("digest", Text, nullable=False),
    Column("signature", Text),
    Column("published_at", Text),
    Column("recalled_at", Text),
)
membership = Table(
    "membership",
    metadata,
    Column("channel", String(160), primary_key=True),
    Column("release_id", ForeignKey("releases.id"), primary_key=True),
)
events = Table(
    "events",
    metadata,
    Column("revision", Integer, primary_key=True, autoincrement=True),
    Column("action", Text, nullable=False),
    Column("release_id", Text, nullable=False),
    Column("channel", Text),
    Column("reason", Text, nullable=False),
    Column("occurred_at", Text, nullable=False),
)
event_actors = Table(
    "release_event_actor",
    metadata,
    Column("revision", ForeignKey("events.revision"), primary_key=True),
    Column("actor", String(160), nullable=False),
)
catalog_metadata = Table(
    "metadata",
    metadata,
    Column("created_at", Text, primary_key=True),
)
catalog_freshness = Table(
    "catalog_freshness",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("ttl_seconds", Integer, nullable=False),
)
deployment_requests = Table(
    "deployment_requests",
    metadata,
    Column("request_id", String(64), primary_key=True),
    Column("subscription_id", String(36), nullable=False),
    Column("release_id", String(64), nullable=False),
    Column("channel", String(64), nullable=False),
    Column("region", String(64), nullable=False),
    Column("source_commit", String(40), nullable=False),
    Column("catalog_digest", String(64), nullable=False),
    Column("recorded_at", String(32), nullable=False),
    Column("status", String(16), nullable=False),
    Column("trust", String(24), nullable=False),
)
Index(
    "deployment_requests_order", deployment_requests.c.recorded_at, deployment_requests.c.request_id
)
Index(
    "deployment_requests_subscription_order",
    deployment_requests.c.subscription_id,
    deployment_requests.c.recorded_at,
    deployment_requests.c.request_id,
)

stencil_variants = Table(
    "stencil_variants",
    metadata,
    Column("variant_key", String(160), primary_key=True),
    Column("base_release_version", String(64), nullable=False),
    Column("stencil_id", String(64), nullable=False),
    Column("release_id", String(160), ForeignKey("releases.id"), nullable=False, unique=True),
    Column("stencil_digest", String(80), nullable=False),
    Column("release_digest", String(80), nullable=False),
    Column("source_commit", String(40), nullable=False),
    Column("registered_at", String(40), nullable=False),
    UniqueConstraint(
        "base_release_version",
        "stencil_id",
        name="uq_stencil_variants_base_version_stencil",
    ),
)

stencil_distribution_grants = Table(
    "stencil_distribution_grants",
    metadata,
    Column("installation_id", String(128), primary_key=True),
    Column("grant_id", String(128), nullable=False, unique=True),
    Column("issuer_key_id", String(64), nullable=False),
    Column("customer_principal", String(160), nullable=False),
    Column("allowed_stencil_ids_json", Text, nullable=False),
    Column("allowed_channels_json", Text, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("issued_at", String(40), nullable=False),
    Column("expires_at", String(40), nullable=False),
    Column("revoked", Boolean, nullable=False),
    Column("revocation_reason", Text),
    Column("scope_digest", String(80), nullable=False),
    Column("envelope_json", Text, nullable=False),
    Column("updated_at", String(40), nullable=False),
)

stencil_grant_events = Table(
    "stencil_grant_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("installation_id", String(128), nullable=False),
    Column("grant_id", String(128), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("action", String(32), nullable=False),
    Column("actor", String(160), nullable=False),
    Column("reason", Text, nullable=False),
    Column("occurred_at", String(40), nullable=False),
)

release_workflow_jobs = Table(
    "release_workflow_jobs",
    metadata,
    Column("job_id", String(128), primary_key=True),
    Column("idempotency_key", String(128), nullable=False, unique=True),
    Column("release_id", String(160), nullable=False),
    Column("stencil_id", String(64), nullable=False),
    Column("source_commit", String(40), nullable=False),
    Column("stage", String(32), nullable=False),
    Column("status", String(32), nullable=False),
    Column("input_digest", String(80), nullable=False),
    Column("manifest_digest", String(80), nullable=False),
    Column("actor", String(160), nullable=False),
    Column("error_code", String(128)),
    Column("result_json", Text, nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
)

promotion_run_receipts = Table(
    "promotion_run_receipts",
    metadata,
    Column("receipt_id", String(128), primary_key=True),
    Column("release_id", String(160), nullable=False),
    Column("source_channel", String(64), nullable=False),
    Column("target_channel", String(64), nullable=False),
    Column("allowed", Boolean, nullable=False),
    Column("reason_code", String(128), nullable=False),
    Column("manifest_digest", String(80), nullable=False),
    Column("component_digests_json", Text, nullable=False),
    Column("actor", String(160), nullable=False),
    Column("occurred_at", String(40), nullable=False),
)

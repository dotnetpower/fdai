"""Portable publication tables, including a singleton catalog lock shared by all replicas."""

from sqlalchemy import Column, ForeignKey, Index, Integer, MetaData, String, Table, Text

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

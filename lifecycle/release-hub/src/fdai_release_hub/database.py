"""Portable publication tables, including a singleton catalog lock shared by all replicas."""

from sqlalchemy import Column, ForeignKey, Integer, MetaData, String, Table, Text

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

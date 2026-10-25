"""Optional TUF role tables. They are created by the explicit root installation command.

They never join `database.metadata`: the Release Hub schema revision does not move, an older
binary never reads them, and a Hub that does not use TUF roles carries none of them.
"""

from sqlalchemy import Column, Integer, MetaData, String, Table, Text

role_metadata = MetaData()
catalog_roots = Table(
    "catalog_role_root",
    role_metadata,
    Column("version", Integer, primary_key=True, autoincrement=False),
    Column("payload", Text, nullable=False),
    Column("digest", String(64), nullable=False),
    Column("installed_at", Text, nullable=False),
    Column("actor", String(160), nullable=False),
)
catalog_role_state = Table(
    "catalog_role_state",
    role_metadata,
    Column("id", Integer, primary_key=True),
    Column("root_version", Integer, nullable=False),
    Column("snapshot_version", Integer, nullable=False),
    Column("snapshot_payload", Text),
    Column("timestamp_version", Integer, nullable=False),
    Column("timestamp_payload", Text),
)

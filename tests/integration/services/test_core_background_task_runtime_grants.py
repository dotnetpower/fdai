from __future__ import annotations

import runpy
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION_PATH = (
    REPO_ROOT / "service-migrations/branches/core-control-plane/versions/"
    "20260826_core_background_task_runtime_grants.py"
)


def test_core_background_task_runtime_grants_are_exact() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    migration = runpy.run_path(str(MIGRATION_PATH))

    assert (
        'down_revision: str | Sequence[str] | None = "core_canonical_incident_projection_20260825"'
        in source
    )
    assert migration["owned_tables"] == ()
    for table in (
        "background_task_attempt",
        "background_task_progress",
        "background_task_completion",
    ):
        assert table in source
    assert "FROM PUBLIC, fdai_core" in source
    assert (
        "GRANT SELECT, INSERT, UPDATE, DELETE\n"
        "            ON TABLE background_task_attempt TO fdai_core" in source
    )
    assert (
        "GRANT SELECT, INSERT\n            ON TABLE background_task_progress TO fdai_core" in source
    )
    assert (
        "GRANT SELECT, INSERT, UPDATE\n"
        "            ON TABLE background_task_completion TO fdai_core" in source
    )
    assert "ON TABLE background_task_progress TO fdai_core;\n        GRANT DELETE" not in source
    assert "ON TABLE background_task_completion TO fdai_core;\n        GRANT DELETE" not in source
    assert "ALTER DEFAULT PRIVILEGES" not in source

"""Fresh-bootstrap contract for the ontology writer compatibility barrier."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_MIGRATION = (
    _ROOT / "service-migrations/branches/core-control-plane/versions/"
    "20260920_core_ontology_writer_fence.py"
)


def test_writer_barrier_builds_numeric_json_without_sqlalchemy_bind_syntax() -> None:
    source = _MIGRATION.read_text(encoding="utf-8")

    assert source.count("jsonb_build_object(") == 2
    assert '"minimum_writer_version":1' not in source

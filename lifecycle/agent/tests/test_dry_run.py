from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from fdai_lifecycle_agent.dry_run import compute_change_set, parse_current_state

if TYPE_CHECKING:
    from conftest import Harness

ARTIFACT = "sha256:" + "b" * 64


def _document(**overrides: object) -> dict[str, Any]:
    document: dict[str, Any] = {
        "digest": "7" * 64,
        "schema_revision": 15,
        "entities": {
            "core": {"release_id": "1.4.0", "artifact_digests": [ARTIFACT], "health": "healthy"}
        },
        "observed_at": "2026-10-01T00:00:00Z",
    }
    document.update(overrides)
    return document


def test_hub_reported_state_shape_is_accepted() -> None:
    state = parse_current_state(_document())

    assert state.digest == "7" * 64
    assert state.entities["core"].artifact_digests == frozenset({ARTIFACT})


def _entity(**overrides: object) -> dict[str, object]:
    entity: dict[str, object] = {
        "release_id": "1.4.0",
        "artifact_digests": [ARTIFACT],
        "health": "healthy",
    }
    entity.update(overrides)
    return {"core": entity}


@pytest.mark.parametrize(
    ("document", "message"),
    [
        (_document(extra=1), "MUST contain digest"),
        (_document(digest="sha256:" + "7" * 64), "64 lowercase hex"),
        (_document(digest="A" * 64), "64 lowercase hex"),
        (_document(schema_revision=-1), "non-negative"),
        (_document(schema_revision=True), "non-negative"),
        (_document(observed_at="2026-10-01T00:00:00"), "timezone"),
        (_document(observed_at="yesterday"), "ISO 8601"),
        (_document(entities=[]), "entities MUST be an object"),
        (_document(entities=_entity(health="fine")), "health is unsupported"),
        (_document(entities=_entity(release_id="")), "non-empty"),
        (_document(entities=_entity(artifact_digests=["latest"])), "sha256:<hex>"),
        (_document(entities={"core": {"release_id": "1.4.0"}}), "MUST contain release_id"),
    ],
)
def test_invalid_current_state_is_refused(document: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_current_state(document)


def test_entity_with_its_own_target_release_images_is_unchanged(harness: Harness) -> None:
    entity_images = {"core": frozenset({ARTIFACT}), "new": frozenset({"sha256:" + "c" * 64})}
    plan = harness.plan(entity_ids=frozenset({"core", "new"}), target_release_id="1.4.0")

    change_set = compute_change_set(plan, entity_images, parse_current_state(_document()))

    assert [(change.entity_id, change.action) for change in change_set.changes] == [
        ("core", "unchanged"),
        ("new", "create"),
    ]

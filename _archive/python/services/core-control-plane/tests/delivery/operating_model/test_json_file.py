from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from types import SimpleNamespace

import pytest
from fdai.delivery.operating_model import (
    JsonOperatingModelProvider,
    JsonOperatingModelProviderConfig,
    operating_intent_source_document_from_mapping,
)
from fdai.delivery.operating_model.json_file import operating_model_snapshot_from_mapping

REPO_ROOT = Path(__file__).resolve().parents[5]


async def test_json_provider_loads_versioned_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "operating-model.json"
    path.write_text(
        json.dumps(
            {
                "source_revision": "revision-1",
                "objects": [
                    {
                        "id": "resource-example",
                        "object_type": "Resource",
                        "properties": {"id": "resource-example", "type": "app-service"},
                    }
                ],
                "links": [],
            }
        ),
        encoding="utf-8",
    )

    snapshot = await JsonOperatingModelProvider(
        config=JsonOperatingModelProviderConfig(path=path)
    ).load()

    assert snapshot.source_revision == "revision-1"
    assert snapshot.objects[0].id == "resource-example"


async def test_cross_runtime_service_catalog_example_is_provider_valid() -> None:
    snapshot = await JsonOperatingModelProvider(
        config=JsonOperatingModelProviderConfig(
            path=(REPO_ROOT / "examples" / "operating-model" / "cross-runtime-service-catalog.json")
        )
    ).load()

    assert snapshot.source_revision == "service-catalog:example@1.0.0"
    assert {item.object_type for item in snapshot.objects} >= {
        "BusinessService",
        "Workload",
        "Resource",
    }
    assert {
        item.properties.get("type") for item in snapshot.objects if item.object_type == "Resource"
    } == {
        "compute.web-app",
        "compute.container-app",
        "kubernetes.deployment",
        "kubernetes.service",
        "kubernetes.pod",
    }
    assert len(snapshot.links) == 6


async def test_json_provider_rejects_oversized_file(tmp_path: Path) -> None:
    path = tmp_path / "operating-model.json"
    path.write_text("{}", encoding="utf-8")
    provider = JsonOperatingModelProvider(
        config=JsonOperatingModelProviderConfig(path=path, max_bytes=1)
    )

    with pytest.raises(ValueError, match="max_bytes"):
        await provider.load()


async def test_json_provider_enforces_read_bound_when_stat_is_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "operating-model.json"
    path.write_text(
        json.dumps(
            {
                "source_revision": "revision-1",
                "objects": [],
                "links": [],
                "padding": "x" * 1024,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "stat", lambda self: SimpleNamespace(st_size=1))
    provider = JsonOperatingModelProvider(
        config=JsonOperatingModelProviderConfig(path=path, max_bytes=128)
    )

    with pytest.raises(ValueError, match="max_bytes"):
        await provider.load()


async def test_json_provider_rejects_excessive_parser_nesting(tmp_path: Path) -> None:
    path = tmp_path / "operating-model.json"
    nested = '{"next":' * 1_100 + '"leaf"' + "}" * 1_100
    path.write_text(
        '{"source_revision":"revision-1","objects":['
        '{"id":"resource-example","object_type":"Resource","properties":'
        + nested
        + '}],"links":[]}',
        encoding="utf-8",
    )
    provider = JsonOperatingModelProvider(config=JsonOperatingModelProviderConfig(path=path))

    with pytest.raises(ValueError, match="bounded canonical JSON"):
        await provider.load()


async def test_json_provider_rejects_duplicate_object_keys(tmp_path: Path) -> None:
    path = tmp_path / "operating-model.json"
    path.write_text(
        '{"source_revision":"revision-1","source_revision":"revision-2","objects":[],"links":[]}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="bounded canonical JSON"):
        await JsonOperatingModelProvider(config=JsonOperatingModelProviderConfig(path=path)).load()


async def test_json_provider_rejects_duplicate_link_identity(tmp_path: Path) -> None:
    path = tmp_path / "operating-model.json"
    link = {
        "link_type": "implemented_by",
        "from_id": "service-example",
        "to_id": "workload-example",
    }
    path.write_text(
        json.dumps(
            {
                "source_revision": "revision-1",
                "objects": [],
                "links": [link, link],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="link identities MUST be unique"):
        await JsonOperatingModelProvider(config=JsonOperatingModelProviderConfig(path=path)).load()


def test_operating_model_accepts_bounded_logical_target_aliases() -> None:
    snapshot = operating_model_snapshot_from_mapping(
        {
            "source_revision": "revision-1",
            "objects": [
                {
                    "id": "service:example",
                    "object_type": "BusinessService",
                    "properties": {
                        "id": "service:example",
                        "name": "Example service",
                        "aliases": ["example backend", "example-api"],
                    },
                }
            ],
            "links": [],
        }
    )

    assert snapshot.objects[0].properties["aliases"] == [
        "example backend",
        "example-api",
    ]


@pytest.mark.parametrize(
    "aliases",
    [
        [],
        ["duplicate", "DUPLICATE"],
        [" padded"],
        ["line\nbreak"],
        ["tab\tbreak"],
        ["null\0break"],
        ["zero\u200bwidth"],
        [unicodedata.normalize("NFD", "é")],
        ["x" * 257],
        [f"alias-{index}" for index in range(33)],
        [1],
    ],
)
def test_operating_model_rejects_malformed_logical_target_aliases(
    aliases: list[object],
) -> None:
    with pytest.raises(ValueError, match="logical target aliases"):
        operating_model_snapshot_from_mapping(
            {
                "source_revision": "revision-1",
                "objects": [
                    {
                        "id": "workload:example",
                        "object_type": "Workload",
                        "properties": {
                            "id": "workload:example",
                            "name": "Example backend",
                            "aliases": aliases,
                        },
                    }
                ],
                "links": [],
            }
        )


def _intent_document() -> dict[str, object]:
    return {
        "source_revision": "operating-intent-revision-1",
        "provenance": {
            "source_url": "https://example.invalid/operating-intent-source",
            "resolved_ref": "operating-intent-revision-1",
            "retrieved_at": "2026-08-27T12:00:00+00:00",
        },
        "objects": [
            {
                "id": "service-objective-1",
                "object_type": "ServiceObjective",
                "properties": {"id": "service-objective-1"},
            }
        ],
        "links": [
            {
                "link_type": "objective_owned_by",
                "from_id": "service-objective-1",
                "to_id": "ownership-1",
                "properties": {},
            }
        ],
    }


def test_intent_source_parses_its_recognized_members() -> None:
    document = operating_intent_source_document_from_mapping(_intent_document())

    assert document.snapshot.source_revision == "operating-intent-revision-1"
    assert document.provenance.resolved_ref == "operating-intent-revision-1"
    assert document.snapshot.objects[0].id == "service-objective-1"
    assert document.snapshot.links[0].link_type == "objective_owned_by"


@pytest.mark.parametrize(
    ("mutate", "label"),
    [
        (lambda raw: raw.update({"annotations": {"note": "unreviewed"}}), "document"),
        (lambda raw: raw["provenance"].update({"signature": "unreviewed"}), "provenance"),
        (lambda raw: raw["objects"][0].update({"revision": 7}), "object entry"),
        (
            lambda raw: raw["objects"][0].update({"type_ref": {"name": "ServiceObjective"}}),
            "object",
        ),
        (lambda raw: raw["links"][0].update({"type_ref": {"name": "objective_owned_by"}}), "link"),
    ],
)
def test_intent_source_rejects_unknown_members_at_every_level(mutate, label: str) -> None:
    """A discarded member would leave the advertised whole-document pin unchanged.

    Each mutation adds content the previous lossy parser dropped before the digest
    was computed, so the pinned `FDAI_OPERATING_INTENT_SOURCE_SHA256` stayed constant
    while the file on disk changed. Rejecting the document is what makes the digest
    cover every accepted member.
    """

    raw = _intent_document()
    mutate(raw)

    with pytest.raises(ValueError, match="unknown members"):
        operating_intent_source_document_from_mapping(raw)


def test_the_generic_operating_model_snapshot_stays_tolerant(tmp_path: Path) -> None:
    """Only the pinned intent source is strict; the generic format is unpinned."""

    path = tmp_path / "operating-model.json"
    path.write_text(
        json.dumps(
            {
                "source_revision": "revision-1",
                "objects": [
                    {
                        "id": "resource-example",
                        "object_type": "Resource",
                        "properties": {"id": "resource-example"},
                        "future_member": True,
                    }
                ],
                "links": [],
                "future_document_member": True,
            }
        ),
        encoding="utf-8",
    )

    snapshot = operating_model_snapshot_from_mapping(
        json.loads(path.read_text(encoding="utf-8")),
    )

    assert snapshot.objects[0].id == "resource-example"

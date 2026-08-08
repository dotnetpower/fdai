from __future__ import annotations

import json
from pathlib import Path

import pytest
from fdai.delivery.operating_model import (
    JsonOperatingModelProvider,
    JsonOperatingModelProviderConfig,
)


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


async def test_json_provider_rejects_oversized_file(tmp_path: Path) -> None:
    path = tmp_path / "operating-model.json"
    path.write_text("{}", encoding="utf-8")
    provider = JsonOperatingModelProvider(
        config=JsonOperatingModelProviderConfig(path=path, max_bytes=1)
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

"""Document-ingestion Event Hubs role scope contracts."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_MAIN = _ROOT / "infra/main.tf"


def _resource_block(source: str, resource_type: str, name: str) -> str:
    marker = f'resource "{resource_type}" "{name}" {{'
    start = source.index(marker)
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"unterminated Terraform resource block: {name}")


def test_ingestion_consumers_receive_from_the_physical_pantheon_topic() -> None:
    source = _MAIN.read_text(encoding="utf-8")
    cohost = _resource_block(source, "azurerm_role_assignment", "ingestion_eventhubs_receiver")
    worker = _resource_block(
        source,
        "azurerm_role_assignment",
        "ingestion_worker_pantheon_receiver",
    )
    retired = _resource_block(
        source,
        "azurerm_role_assignment",
        "ingestion_worker_eventhubs_receiver",
    )

    expected_scope = 'scope                = module.event_bus.topic_ids["aw.pantheon.objects"]'
    assert expected_scope in cohost
    assert expected_scope in worker
    assert "count                = 0" in retired
    assert 'auxiliary_topic_ids["aw.pipeline.stages"]' in retired

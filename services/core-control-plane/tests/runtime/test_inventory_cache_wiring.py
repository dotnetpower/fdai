from __future__ import annotations

from fdai.delivery.inventory_cache_invalidation import InvalidatingInventoryDeltaProjector
from fdai.delivery.persistence.postgres_inventory_delta import PostgresInventoryDeltaProjector
from fdai.runtime.providers import _build_inventory_delta_projector


def _configure_inventory_projector(monkeypatch, *, runtime_env: str) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("FDAI_INVENTORY_DSN", raising=False)
    monkeypatch.delenv("FDAI_LOCAL_AZURE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("FDAI_STATE_STORE_DSN", "postgresql://example.invalid/fdai")
    monkeypatch.setenv("FDAI_RUNTIME_LOCAL_AZURE_CLI", "1")
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "subscription-example")
    monkeypatch.setenv("RUNTIME_ENV", runtime_env)


def test_local_inventory_projector_invalidates_its_account_cache(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _configure_inventory_projector(monkeypatch, runtime_env="dev")

    projector = _build_inventory_delta_projector()

    assert isinstance(projector, InvalidatingInventoryDeltaProjector)
    assert projector._marker_path.parent.name == "inventory"
    assert projector._marker_path.suffix == ".invalidated"
    assert "subscription-example" not in projector._marker_path.name


def test_deployed_inventory_projector_does_not_write_local_cache_markers(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _configure_inventory_projector(monkeypatch, runtime_env="prod")

    projector = _build_inventory_delta_projector()

    assert isinstance(projector, PostgresInventoryDeltaProjector)

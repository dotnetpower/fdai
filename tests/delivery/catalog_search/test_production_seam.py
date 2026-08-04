from __future__ import annotations

from typing import Any, cast

from starlette.applications import Starlette

from fdai.delivery.operator_api import prod
from fdai.delivery.operator_api.production import factory
from fdai.shared.providers.catalog_search import CatalogSemanticIndex


def test_production_facade_forwards_catalog_semantic_index(monkeypatch: Any) -> None:
    marker = cast(CatalogSemanticIndex, object())
    application = Starlette()
    captured: dict[str, object] = {}

    def _build(
        environ: object = None,
        *,
        catalog_semantic_index: CatalogSemanticIndex | None = None,
    ) -> Starlette:
        captured["environ"] = environ
        captured["index"] = catalog_semantic_index
        return application

    monkeypatch.setattr(factory, "build_prod_app", _build)

    assert prod.build_prod_app({}, catalog_semantic_index=marker) is application
    assert captured == {"environ": {}, "index": marker}

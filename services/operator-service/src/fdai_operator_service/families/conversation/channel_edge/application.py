"""Public ASGI factory for the standalone Operator channel edge."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Protocol

from fdai_operator_service.families.conversation.channel_edge.composition import (
    ProductionChannelEdgeComposition,
)
from fdai_operator_service.families.conversation.channel_edge.runtime import (
    ChannelEdgeHttpRuntime,
    create_channel_edge_app,
)
from starlette.applications import Starlette


class ChannelEdgeComposition(Protocol):
    """Build one fully configured edge runtime from an environment snapshot."""

    def build_runtime(
        self,
        environ: Mapping[str, str] | None = None,
    ) -> ChannelEdgeHttpRuntime: ...


def create_app(
    environ: Mapping[str, str] | None = None,
    *,
    composition: ChannelEdgeComposition | None = None,
) -> Starlette:
    """Validate and compose the standalone public webhook application."""
    selected = composition or ProductionChannelEdgeComposition()
    runtime = selected.build_runtime(os.environ if environ is None else environ)
    return create_channel_edge_app(runtime)


__all__ = ["create_app"]

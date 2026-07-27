"""SREGym plugin for the brand-neutral FDAI benchmark runner."""

from fdai_bench_sregym.adapter import SregymAdapter, SregymAdapterConfig
from fdai_bench_sregym.plugin import SregymPlugin, create_plugin

__all__ = [
    "SregymAdapter",
    "SregymAdapterConfig",
    "SregymPlugin",
    "create_plugin",
]

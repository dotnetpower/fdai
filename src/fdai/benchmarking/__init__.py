"""Brand-neutral benchmark runner contracts and plugin loading."""

from fdai.benchmarking.adapter import BenchmarkAdapter
from fdai.benchmarking.bindings import BenchmarkBindings, bind_benchmark_providers
from fdai.benchmarking.contracts import (
    BenchmarkStatus,
    BenchmarkSubmission,
    BenchmarkTask,
    validate_benchmark_identifier,
)
from fdai.benchmarking.plugins import (
    BENCHMARK_API_VERSION,
    BENCHMARK_ENTRY_POINT_GROUP,
    BenchmarkPlugin,
    BenchmarkPluginError,
    discover_benchmark_plugins,
    load_benchmark_plugin,
)
from fdai.benchmarking.runner import (
    BenchmarkRunError,
    BenchmarkRunner,
    BenchmarkRunSummary,
    BenchmarkTaskProcessor,
)

__all__ = [
    "BENCHMARK_API_VERSION",
    "BENCHMARK_ENTRY_POINT_GROUP",
    "BenchmarkAdapter",
    "BenchmarkBindings",
    "BenchmarkPlugin",
    "BenchmarkPluginError",
    "BenchmarkRunError",
    "BenchmarkRunner",
    "BenchmarkRunSummary",
    "BenchmarkStatus",
    "BenchmarkSubmission",
    "BenchmarkTask",
    "BenchmarkTaskProcessor",
    "bind_benchmark_providers",
    "discover_benchmark_plugins",
    "load_benchmark_plugin",
    "validate_benchmark_identifier",
]

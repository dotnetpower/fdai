"""Repository tests with explicit access to Core service test helpers."""

from pathlib import Path

__path__.append(str(Path(__file__).resolve().parents[1] / "services/core-control-plane/tests"))

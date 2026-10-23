"""Make the Lifecycle Manager source package importable during root test collection."""

from __future__ import annotations

import sys
from pathlib import Path

_SOURCE_ROOT = str(Path(__file__).resolve().parent / "src")

if _SOURCE_ROOT in sys.path:
    sys.path.remove(_SOURCE_ROOT)
sys.path.insert(0, _SOURCE_ROOT)

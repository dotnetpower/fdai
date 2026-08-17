"""Locate repository-shipped runtime assets from an installed package."""

from __future__ import annotations

from pathlib import Path

_ASSET_MARKERS = ("rule-catalog", "config")


def repo_asset_root(start: Path | None = None) -> Path:
    """Return the directory that carries the shipped asset trees.

    A checkout keeps them at the repository root, while the container image
    keeps them beside the virtual environment, so a fixed parent depth from the
    package resolves to the wrong directory in one of the two layouts.
    """

    origin = (start or Path(__file__)).resolve()
    for candidate in origin.parents:
        if all((candidate / marker).is_dir() for marker in _ASSET_MARKERS):
            return candidate
    raise FileNotFoundError(f"repository asset root not found above {origin}")


__all__ = ["repo_asset_root"]

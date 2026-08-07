"""Canonical immutable Change lineage with no authority-bearing behavior."""

from .models import ChangeLineageRecord, build_change_lineage

__all__ = ["ChangeLineageRecord", "build_change_lineage"]

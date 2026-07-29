"""MCSB runtime observation registry tests."""

from __future__ import annotations

import re

import pytest

from fdai.delivery.azure.security_posture_mcsb import (
    MCSB_CONTROLS_BY_OBSERVATION,
    mcsb_controls,
)

_MCSB_ID = re.compile(r"^MCSB-(NS|IM|PA|DP|AM|LT|IR|PV|ES|BR|DS|GS|AI)-[1-9][0-9]*$")


def test_registry_contains_only_canonical_control_ids() -> None:
    assert len(MCSB_CONTROLS_BY_OBSERVATION) == 9
    assert all(
        _MCSB_ID.fullmatch(control_id)
        for control_ids in MCSB_CONTROLS_BY_OBSERVATION.values()
        for control_id in control_ids
    )


def test_lookup_fails_closed_for_unreviewed_observation() -> None:
    with pytest.raises(ValueError, match="unknown MCSB observation id"):
        mcsb_controls("unreviewed")

"""Retention for Forseti's per-event no-rule fold markers."""

from __future__ import annotations

import hashlib
from typing import Final

from fdai.shared.providers.state_store import StateStore

# A marker only de-duplicates one event's no-rule verdict, so a bounded newest window is enough.
NO_RULE_FOLD_PREFIX: Final = "pantheon/forseti/no-rule-fold|"
NO_RULE_FOLD_RETENTION: Final = 20_000
_SWEEP_MODULUS: Final = 256


async def sweep_no_rule_folds(store: StateStore, fold_key: str) -> None:
    """Trim old markers for about 1 in 256 new ones, without needing a counter."""
    if int(hashlib.sha256(fold_key.encode()).hexdigest()[:8], 16) % _SWEEP_MODULUS == 0:
        await store.delete_states_beyond(NO_RULE_FOLD_PREFIX, retain_newest=NO_RULE_FOLD_RETENTION)


__all__ = ["NO_RULE_FOLD_PREFIX", "NO_RULE_FOLD_RETENTION", "sweep_no_rule_folds"]

"""The audit hash-chain rule, shared by every StateStore backend.

The in-memory backend and the PostgreSQL backend each carried their own copy of
the genesis constant, the canonical serialization, and the chaining hash. Those
copies have to agree exactly: a chain written by one backend is verified by the
other after a migration, and one whitespace or key-ordering difference would
report a perfectly intact log as tampered. Two copies of a rule that must not
differ is a rule waiting to differ.

Nothing here changes how a hash is computed - the copies were identical, so
existing chains verify unchanged.

The ``default=str`` fallback is deliberate rather than silently relied upon: it
makes an otherwise unserializable value hashable, at the cost of collapsing a
value and its string form to one digest. No production path reaches it - a
full-suite probe that raised instead of falling back found only a test that
exercises the fallback on purpose - so it stays a backstop rather than a hole
anything currently walks through.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Final

GENESIS_HASH: Final[str] = "0" * 64
"""The previous-hash of the first entry in any chain."""


def canonical_entry(entry: Mapping[str, Any]) -> str:
    """Serialize one audit entry to the exact bytes the chain hashes."""
    return json.dumps(dict(entry), sort_keys=True, separators=(",", ":"), default=str)


def next_hash(previous: str, entry: Mapping[str, Any]) -> str:
    """Return the entry hash that chains ``entry`` onto ``previous``."""
    return hashlib.sha256((previous + canonical_entry(entry)).encode("utf-8")).hexdigest()


__all__ = ["GENESIS_HASH", "canonical_entry", "next_hash"]

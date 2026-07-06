"""Operator memory seam for the T2 tier.

Operator memory captures **scope-bounded, HIL-approved** guidance
derived from operator interactions (HIL reject reasons, override
justifications, ChatOps preferences, PR review comments) and injects
it into the composed prompt as a data layer the model MUST treat as
untrusted. The design lives in
``docs/roadmap/prompt-composition.md § Operator memory pipeline``.

Wave 3 step A introduces the types, the async :class:`OperatorMemoryStore`
:class:`~typing.Protocol`, an in-memory implementation for tests, and
the sanitizer that wraps every retrieved entry in
``<operator_note trusted="false" ...>...</operator_note>`` before it
reaches the model. The Postgres-backed store, the HIL second-approval
pipeline, and the composer integration land in later steps.

Design references:

- ``docs/roadmap/prompt-composition.md § Operator memory pipeline``
- ``.github/instructions/architecture.instructions.md § Human Override``
- ``.github/instructions/coding-conventions.instructions.md § Safety``
"""

from __future__ import annotations

from aiopspilot.core.operator_memory.hil_pipeline import (
    HilMaterializationError,
    HilRejectMaterial,
    HilRejectMaterializer,
)
from aiopspilot.core.operator_memory.sanitizer import (
    InjectionMarkerError,
    detect_injection_markers,
    wrap_operator_note,
)
from aiopspilot.core.operator_memory.store import (
    InMemoryOperatorMemoryStore,
    OperatorMemoryPolicyError,
    OperatorMemoryStore,
)
from aiopspilot.core.operator_memory.types import (
    MemoryCategory,
    MemorySource,
    OperatorMemoryEntry,
    OperatorScope,
    ScopeKind,
)

__all__ = [
    "HilMaterializationError",
    "HilRejectMaterial",
    "HilRejectMaterializer",
    "InMemoryOperatorMemoryStore",
    "InjectionMarkerError",
    "MemoryCategory",
    "MemorySource",
    "OperatorMemoryEntry",
    "OperatorMemoryPolicyError",
    "OperatorMemoryStore",
    "OperatorScope",
    "ScopeKind",
    "detect_injection_markers",
    "wrap_operator_note",
]

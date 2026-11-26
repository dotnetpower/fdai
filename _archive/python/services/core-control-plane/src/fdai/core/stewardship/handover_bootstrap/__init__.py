"""Handover-bootstrap - parse ops docs into a draft steward map (issue #23).

Larger, separable capability on top of the deterministic stewardship core:
an operator uploads existing operational documents (RACI matrices, on-call
schedules, org charts, runbooks, handover memos) and FDAI parses them into a
**draft** human <-> agent steward map for review.

Deterministic-first, grounded, and abstaining: structured extraction runs
before any model, every mapping cites its source span, low-confidence mappings
and unresolved people/agents are surfaced rather than guessed, and the output
is never applied - it is a governance draft PR a human reviews (the console
stays read-only, per app-shape rules).

Public surface:

- :class:`HandoverBootstrapper` - the orchestrator (documents in, draft out).
- :func:`render_draft_yaml` - render the draft as resolver-loadable YAML.
- Seams a fork binds: :class:`HandoverInterpreter` (T2 model),
  :class:`PersonDirectory` (name -> Entra object id).
- Contracts: :class:`HandoverDocument`, :class:`StewardMapDraft`,
  :class:`ExtractedMapping`, and friends.
"""

from __future__ import annotations

from fdai.core.stewardship.handover_bootstrap.bootstrap import HandoverBootstrapper
from fdai.core.stewardship.handover_bootstrap.contract import (
    DocumentKind,
    DraftOutcome,
    ExtractedMapping,
    HandoverDocument,
    MappingSource,
    PersonRef,
    SourceSpan,
    StewardMapDraft,
)
from fdai.core.stewardship.handover_bootstrap.draft_yaml import (
    render_candidate_yaml,
    render_draft_yaml,
)
from fdai.core.stewardship.handover_bootstrap.extractor import DeterministicExtractor
from fdai.core.stewardship.handover_bootstrap.interpreter import (
    AbstainingInterpreter,
    HandoverInterpreter,
)
from fdai.core.stewardship.handover_bootstrap.people import (
    NullPersonDirectory,
    PersonDirectory,
    ResolvedIdentity,
    StaticPersonDirectory,
)

__all__ = [
    "AbstainingInterpreter",
    "DeterministicExtractor",
    "DocumentKind",
    "DraftOutcome",
    "ExtractedMapping",
    "HandoverBootstrapper",
    "HandoverDocument",
    "HandoverInterpreter",
    "MappingSource",
    "NullPersonDirectory",
    "PersonDirectory",
    "PersonRef",
    "ResolvedIdentity",
    "SourceSpan",
    "StaticPersonDirectory",
    "StewardMapDraft",
    "render_draft_yaml",
    "render_candidate_yaml",
]

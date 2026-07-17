"""Compatibility facade for atomic screen-claim verification.

The implementation is split by responsibility across the sibling
``chat_claim_*`` modules. Imports from this original module remain stable.
"""

# ruff: noqa: F401 - private helpers remain import-compatible during the refactor

from __future__ import annotations

from fdai.delivery.read_api.routes.chat_claim_evidence import (
    MAX_EVIDENCE_ENTRIES as _MAX_EVIDENCE_ENTRIES,
)
from fdai.delivery.read_api.routes.chat_claim_evidence import append_entry as _append_entry
from fdai.delivery.read_api.routes.chat_claim_evidence import collect_evidence as _collect_evidence
from fdai.delivery.read_api.routes.chat_claim_evidence import (
    collect_nested_evidence as _collect_nested_evidence,
)
from fdai.delivery.read_api.routes.chat_claim_evidence import is_ratio_field as _is_ratio_field
from fdai.delivery.read_api.routes.chat_claim_extraction import CAUSAL_RE as _CAUSAL_RE
from fdai.delivery.read_api.routes.chat_claim_extraction import MAX_CLAIMS as _MAX_CLAIMS
from fdai.delivery.read_api.routes.chat_claim_extraction import SCOPE_RE as _SCOPE_RE
from fdai.delivery.read_api.routes.chat_claim_extraction import (
    SCREEN_ABSENCE_RE as _SCREEN_ABSENCE_RE,
)
from fdai.delivery.read_api.routes.chat_claim_extraction import extract_claims as _extract_claims
from fdai.delivery.read_api.routes.chat_claim_extraction import (
    looks_like_non_claim_number as _looks_like_non_claim_number,
)
from fdai.delivery.read_api.routes.chat_claim_extraction import sentence_at as _sentence_at
from fdai.delivery.read_api.routes.chat_claim_extraction import sentences as _sentences
from fdai.delivery.read_api.routes.chat_claim_extraction import window as _window
from fdai.delivery.read_api.routes.chat_claim_manifest import (
    evidence_authority as _evidence_authority,
)
from fdai.delivery.read_api.routes.chat_claim_matching import CAUSAL_FIELDS as _CAUSAL_FIELDS
from fdai.delivery.read_api.routes.chat_claim_matching import (
    causal_evidence_matches as _causal_evidence_matches,
)
from fdai.delivery.read_api.routes.chat_claim_matching import claim as _claim
from fdai.delivery.read_api.routes.chat_claim_matching import (
    narrative_contains as _narrative_contains,
)
from fdai.delivery.read_api.routes.chat_claim_matching import (
    resolve_candidates as _resolve_candidates,
)
from fdai.delivery.read_api.routes.chat_claim_matching import (
    screen_absence_anchors as _screen_absence_anchors,
)
from fdai.delivery.read_api.routes.chat_claim_matching import verify_claim as _verify_claim
from fdai.delivery.read_api.routes.chat_claim_matching import verify_scope as _verify_scope
from fdai.delivery.read_api.routes.chat_claim_models import (
    AtomicClaim,
    ClaimKind,
    ClaimStatus,
    EvidenceEntry,
    EvidenceManifest,
    ScreenClaimResult,
)
from fdai.delivery.read_api.routes.chat_claim_models import (
    ClaimDraft as _ClaimDraft,
)
from fdai.delivery.read_api.routes.chat_claim_text import ANCHOR_STOP as _ANCHOR_STOP
from fdai.delivery.read_api.routes.chat_claim_text import ID_RE as _ID_RE
from fdai.delivery.read_api.routes.chat_claim_text import NUMBER_RE as _NUMBER_RE
from fdai.delivery.read_api.routes.chat_claim_text import PERCENT_RE as _PERCENT_RE
from fdai.delivery.read_api.routes.chat_claim_text import TIMESTAMP_RE as _TIMESTAMP_RE
from fdai.delivery.read_api.routes.chat_claim_text import WORD_RE as _WORD_RE
from fdai.delivery.read_api.routes.chat_claim_text import anchor_overlap as _anchor_overlap
from fdai.delivery.read_api.routes.chat_claim_text import anchor_score as _anchor_score
from fdai.delivery.read_api.routes.chat_claim_text import anchor_token as _anchor_token
from fdai.delivery.read_api.routes.chat_claim_text import anchors as _anchors
from fdai.delivery.read_api.routes.chat_claim_text import decimal_value as _decimal
from fdai.delivery.read_api.routes.chat_claim_text import (
    normalize_claim_value as _normalize_claim_value,
)
from fdai.delivery.read_api.routes.chat_claim_text import normalize_number as _normalize_number
from fdai.delivery.read_api.routes.chat_claim_text import normalize_text as _normalize_text
from fdai.delivery.read_api.routes.chat_claim_text import (
    normalize_timestamp as _normalize_timestamp,
)
from fdai.delivery.read_api.routes.chat_claim_text import optional_text as _optional_text
from fdai.delivery.read_api.routes.chat_claim_text import overlaps as _overlaps
from fdai.delivery.read_api.routes.chat_claim_verifier import verify_screen_claims

__all__ = [
    "AtomicClaim",
    "EvidenceEntry",
    "EvidenceManifest",
    "ScreenClaimResult",
    "verify_screen_claims",
]

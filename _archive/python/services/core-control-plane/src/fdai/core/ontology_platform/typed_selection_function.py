"""Deterministic no-network consumption contract for prepared typed-selection evidence."""

from __future__ import annotations

import hashlib
from pathlib import Path

from fdai.shared.contracts.models import OntologyFunctionType

from .instance_candidate_queries import instance_candidates_function_type
from .typed_selection_contracts import READ_FUNCTION


def typed_selection_function_type(*, object_type_names: tuple[str, ...]) -> OntologyFunctionType:
    """Retain the five-second local reader budget; inference belongs to the preceding stage."""
    return instance_candidates_function_type(object_type_names=object_type_names).model_copy(
        update={
            "name": READ_FUNCTION,
            "artifact_digest": "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }
    )

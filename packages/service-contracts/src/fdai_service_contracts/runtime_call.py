"""Implementation-free identity for runtime-call relationship observations."""

from __future__ import annotations

import hashlib

RUNTIME_CALL_MAPPING_ID = "runtime-call-endpoint-identity"
RUNTIME_CALL_MAPPING_REVISION = "1.1.0"
RUNTIME_CALL_SOURCE_SCHEMA_VERSION = "fdai.runtime-call-observation@1.1.0"
RUNTIME_CALL_VERIFICATION_METHOD = "deterministic-cross-check"
_RUNTIME_CALL_SOURCE_SCHEMA = (
    "observation_id:string;caller_resource_ids:ordered_unique_string_tuple;"
    "target_resource_ids:ordered_unique_string_tuple;scope_ref:string;"
    "observed_at:aware_datetime;evidence_cutoff:aware_datetime;"
    "recorded_at:aware_datetime;freshness_ceiling_seconds:bounded_positive_integer;"
    "source_identity:string;source_revision:string;evidence_ref:string;authentication_ref:string;"
    "execution_authority:false;mutation_authority:false"
)
RUNTIME_CALL_SOURCE_SCHEMA_DIGEST = (
    "sha256:" + hashlib.sha256(_RUNTIME_CALL_SOURCE_SCHEMA.encode("ascii")).hexdigest()
)

__all__ = [
    "RUNTIME_CALL_MAPPING_ID",
    "RUNTIME_CALL_MAPPING_REVISION",
    "RUNTIME_CALL_SOURCE_SCHEMA_DIGEST",
    "RUNTIME_CALL_SOURCE_SCHEMA_VERSION",
    "RUNTIME_CALL_VERIFICATION_METHOD",
]

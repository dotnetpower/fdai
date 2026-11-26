"""Execution provenance binding on durable safeguard dispatch evidence.

FDAI-CONST-007 evidence is only attributable when a durable record names
the matrix cell it belongs to. These tests pin the two properties that make
that safe: a new record always binds both provenance axes, and a record
written before the axes existed still verifies byte-for-byte.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any, cast

import pytest
from fdai.core.executor.execution_provenance import (
    SafeguardExecutionOrigin,
    SafeguardExecutionVenue,
    resolve_execution_origin,
)
from fdai.core.executor.safeguard_dispatch_checkpoint import (
    SafeguardDispatchEvidenceRecord,
)
from fdai.core.executor.safeguard_dispatch_codec import (
    safeguard_dispatch_record_from_mapping,
    safeguard_dispatch_record_to_mapping,
)
from fdai.core.executor.safeguard_dispatch_identity import (
    PROVENANCE_FIELDS,
    SafeguardDispatchEvidenceIdentity,
)
from fdai.core.executor.safeguard_dispatch_support import payload_digest

from tests.core.executor.test_safeguard_dispatch_checkpoint import _bundle_record


def _identity() -> SafeguardDispatchEvidenceIdentity:
    record, _reservation = _bundle_record()
    return record.identity


def _legacy_mapping() -> dict[str, Any]:
    """Reproduce a record written before provenance existed.

    Both digests are recomputed over the narrower body on purpose: that is
    exactly what the 1.0.0 writer hashed, so a decoder that silently hashed
    ``null`` provenance would reject its own history.
    """

    record, _reservation = _bundle_record()
    legacy_identity = replace(
        record.identity,
        schema_version="1.0.0",
        execution_origin=None,
        execution_venue=None,
        identity_digest=_legacy_identity_digest(record.identity),
    )
    legacy_record = replace(
        record,
        identity=legacy_identity,
        record_digest=_legacy_record_digest(record, legacy_identity),
    )
    return safeguard_dispatch_record_to_mapping(legacy_record)


def _legacy_identity_digest(
    identity: SafeguardDispatchEvidenceIdentity,
) -> str:
    body = {
        name: getattr(identity, name)
        for name in identity.__dataclass_fields__
        if name not in PROVENANCE_FIELDS
    }
    body["schema_version"] = "1.0.0"
    return payload_digest(
        body,
        "safeguard-dispatch-evidence-identity",
        digest_field="identity_digest",
    )


def _legacy_record_digest(
    record: SafeguardDispatchEvidenceRecord,
    legacy_identity: SafeguardDispatchEvidenceIdentity,
) -> str:
    body = asdict(record)
    body["identity"] = {
        name: value
        for name, value in asdict(legacy_identity).items()
        if name not in PROVENANCE_FIELDS
    }
    return payload_digest(
        body,
        "safeguard-dispatch-evidence-record",
        digest_field="record_digest",
    )


def test_new_evidence_identity_binds_path_origin_and_venue() -> None:
    identity = _identity()

    assert identity.schema_version == "1.1.0"
    assert identity.execution_path
    assert identity.execution_origin == SafeguardExecutionOrigin.CORE.value
    assert identity.execution_venue == SafeguardExecutionVenue.CORE.value
    assert identity.binds_execution_provenance is True


def test_provenance_survives_a_serialization_round_trip() -> None:
    record, _reservation = _bundle_record()

    restored = safeguard_dispatch_record_from_mapping(safeguard_dispatch_record_to_mapping(record))

    assert restored.identity.execution_origin == record.identity.execution_origin
    assert restored.identity.execution_venue == record.identity.execution_venue
    assert restored.identity.identity_digest == record.identity.identity_digest


def test_a_pre_provenance_identity_still_decodes_and_verifies() -> None:
    mapping = _legacy_mapping()

    identity = safeguard_dispatch_record_from_mapping(mapping).identity

    assert identity.schema_version == "1.0.0"
    assert identity.execution_origin is None
    assert identity.execution_venue is None
    assert identity.binds_execution_provenance is False


def test_a_pre_provenance_identity_may_not_smuggle_provenance() -> None:
    mapping = _legacy_mapping()
    cast(dict[str, Any], mapping["identity"])["execution_origin"] = "core"

    with pytest.raises(ValueError, match="identity fields are invalid"):
        safeguard_dispatch_record_from_mapping(mapping)


def test_a_current_identity_may_not_omit_provenance() -> None:
    record, _reservation = _bundle_record()
    mapping = safeguard_dispatch_record_to_mapping(record)
    cast(dict[str, Any], mapping["identity"]).pop("execution_venue")

    with pytest.raises(ValueError, match="identity fields are invalid"):
        safeguard_dispatch_record_from_mapping(mapping)


@pytest.mark.parametrize(
    ("field", "tampered"),
    (
        ("execution_origin", SafeguardExecutionOrigin.WORKFLOW.value),
        ("execution_venue", SafeguardExecutionVenue.ISOLATED_EXECUTOR.value),
    ),
)
def test_tampering_with_provenance_breaks_the_identity_digest(
    field: str,
    tampered: str,
) -> None:
    identity = _identity()
    values = dict(_identity_values(identity))
    values[field] = tampered

    with pytest.raises(ValueError, match="identity digest mismatched"):
        SafeguardDispatchEvidenceIdentity(**values)  # type: ignore[arg-type]


def _identity_values(
    identity: SafeguardDispatchEvidenceIdentity,
) -> dict[str, Any]:
    return {name: getattr(identity, name) for name in identity.__dataclass_fields__}


@pytest.mark.parametrize(
    ("origin", "venue"),
    (
        ("not-an-origin", SafeguardExecutionVenue.CORE.value),
        (SafeguardExecutionOrigin.CORE.value, "not-a-venue"),
    ),
)
def test_unknown_provenance_values_are_refused(origin: str, venue: str) -> None:
    identity = _identity()
    values = dict(_identity_values(identity))
    values.pop("identity_digest")
    values["execution_origin"] = origin
    values["execution_venue"] = venue
    values["identity_digest"] = payload_digest(
        values,
        "safeguard-dispatch-evidence-identity",
        digest_field="identity_digest",
    )

    with pytest.raises(ValueError, match="execution provenance is invalid"):
        SafeguardDispatchEvidenceIdentity(**values)  # type: ignore[arg-type]


def test_workflow_lineage_selects_the_workflow_origin() -> None:
    class _Lineage:
        workflow_action = object()

    assert resolve_execution_origin(cast(Any, _Lineage())) is SafeguardExecutionOrigin.WORKFLOW


def test_absent_workflow_lineage_selects_the_core_origin() -> None:
    class _NoLineage:
        workflow_action = None

    assert resolve_execution_origin(cast(Any, _NoLineage())) is SafeguardExecutionOrigin.CORE

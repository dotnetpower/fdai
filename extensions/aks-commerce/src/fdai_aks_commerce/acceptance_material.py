"""Immutable Forseti-owned Action material; retention never supplies execution authority."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from uuid import UUID

from fdai.runtime.isolated_executor_receipt_journal import BoundCommandCorrelation
from fdai.shared.contracts.models import Action, Operation
from fdai.shared.providers.state_store import StateStore

_PREFIX = "aks-commerce:acceptance-action:v1:"


@dataclass(frozen=True, slots=True)
class AcceptanceDispatchMaterial:
    """Keep Action identity distinct from its immutable anomaly/ActionRun correlation binding."""

    action_json: str
    correlation_id: str
    action_run_idempotency_key: str
    rule_digest: str | None = None
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            len(self.evidence_refs) > 12
            or len(set(self.evidence_refs)) != len(self.evidence_refs)
            or any(
                not isinstance(value, str) or not value or len(value) > 512
                for value in self.evidence_refs
            )
        ):
            raise ValueError("acceptance material requires bounded distinct observation references")
        if self.rule_digest is not None and (
            not self.rule_digest.startswith("sha256:")
            or len(self.rule_digest) != 71
            or any(character not in "0123456789abcdef" for character in self.rule_digest[7:])
        ):
            raise ValueError("acceptance material requires a canonical Rule digest")
        for reference in (self.correlation_id, self.action_run_idempotency_key):
            if (
                not isinstance(reference, str)
                or not reference
                or reference != reference.strip()
                or len(reference) > 512
            ):
                raise ValueError("acceptance material requires exact bounded lineage")
        self.action()

    def action(self) -> Action:
        """Decode a fresh Action without exposing mutable stored material to callers."""
        if not isinstance(self.action_json, str) or len(self.action_json) > 65_536:
            raise ValueError("acceptance material Action exceeds its bound")
        action = Action.model_validate_json(self.action_json)
        if (
            action.action_type != "ops.scale-out"
            or action.operation is not Operation.SCALE
            or action.model_dump_json() != self.action_json
        ):
            raise ValueError("acceptance material requires a canonical registered scale Action")
        return action


class StoredAcceptanceDispatchMaterials:
    """Retain original prepared Actions with atomic audit and reject replacement or corruption.

    Only the Forseti-owned preparation binding writes these inert records. Reader access and a
    valid digest grant no promotion or approval; dispatch separately rechecks current authority.
    """

    def __init__(self, store: StateStore) -> None:
        self._store = store

    async def retain(self, material: AcceptanceDispatchMaterial) -> None:
        """Write once with exact replay readback; never update approved material."""
        action = material.action()
        record = _record(material)
        key = _PREFIX + str(action.action_id)
        created = await self._store.write_state_with_audit_if_absent(
            key,
            record,
            {
                "actor": "Forseti",
                "action_kind": "aks_commerce.action_material.retained",
                "action_id": str(action.action_id),
                "material_digest": record["digest"],
                "mode": action.mode.value,
                "execution_authority": False,
            },
        )
        if not created and await self._store.read_state(key) != record:
            raise ValueError("acceptance original Action material already binds different content")

    async def read(self, action_id: str) -> AcceptanceDispatchMaterial | None:
        """Read only the exact UUID-keyed original; absence never builds a replacement Action."""
        canonical_id = str(UUID(action_id))
        if canonical_id != action_id:
            raise ValueError("acceptance Action id must be canonical")
        record = await self._store.read_state(_PREFIX + canonical_id)
        if record is None:
            return None
        raw = record.get("material")
        if (
            set(record) != {"schema_version", "material", "digest"}
            or record["schema_version"] != "1.0.0"
            or not isinstance(raw, dict)
            or set(raw)
            not in (
                {"action_json", "correlation_id", "action_run_idempotency_key", "rule_digest"},
                {
                    "action_json",
                    "correlation_id",
                    "action_run_idempotency_key",
                    "rule_digest",
                    "evidence_refs",
                },
            )
        ):
            raise ValueError("acceptance original Action material is malformed")
        values = dict(raw)
        if "evidence_refs" in values:
            if not isinstance(values["evidence_refs"], list):
                raise ValueError("acceptance observation references must be a JSON array")
            values["evidence_refs"] = tuple(values["evidence_refs"])
        material = AcceptanceDispatchMaterial(**values)
        if str(material.action().action_id) != canonical_id or record != _record(material):
            raise ValueError("acceptance original Action material integrity mismatch")
        return material

    async def link_command(self, action: Action, command_id: str) -> None:
        """Retain only the command independently read back from Core's original command journal."""
        if str(UUID(command_id)) != command_id:
            raise ValueError("acceptance command id must be canonical")
        material = await self.read(str(action.action_id))
        raw = await self._store.read_state("runtime:isolated-executor:command:" + command_id)
        if material is None or material.action_json != action.model_dump_json() or raw is None:
            raise ValueError("acceptance original command readback is unavailable")
        correlation = BoundCommandCorrelation.model_validate(raw)
        if str(
            correlation.command.command_id
        ) != command_id or correlation.command.action_payload != action.model_dump(
            mode="json", exclude_none=True
        ):
            raise ValueError("acceptance command changed the original Action")
        key = "aks-commerce:acceptance-command:v1:" + str(action.action_id)
        record = {"command_id": command_id, "closure_key": correlation.closure_key}
        created = await self._store.write_state_with_audit_if_absent(
            key,
            record,
            {
                "actor": "Thor",
                "action_kind": "aks_commerce.command.linked",
                "action_id": str(action.action_id),
                "command_id": command_id,
                "execution_authority": False,
            },
        )
        if not created and await self._store.read_state(key) != record:
            raise ValueError("acceptance original Action already has a different command")


def _record(material: AcceptanceDispatchMaterial) -> dict[str, object]:
    payload = asdict(material)
    if material.evidence_refs:
        payload["evidence_refs"] = list(material.evidence_refs)
    else:
        payload.pop("evidence_refs")
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    return {"schema_version": "1.0.0", "material": payload, "digest": "sha256:" + digest}

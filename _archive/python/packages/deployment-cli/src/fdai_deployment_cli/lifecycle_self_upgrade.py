"""Dual-slot self-upgrade controller for installation agents and Target Hubs."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal

from fdai_deployment_cli.runtime_release import is_release_id

SelfUpgradeComponent = Literal["lifecycle-agent", "infrastructure-agent", "target-hub"]
SlotId = Literal["slot-a", "slot-b"]
SelfUpgradeOutcome = Literal["upgraded", "rolled-back"]

_SUPPORTED_COMPONENTS = frozenset({"lifecycle-agent", "infrastructure-agent", "target-hub"})
_IMAGE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z", re.ASCII)


def _other_slot(slot: SlotId) -> SlotId:
    return "slot-b" if slot == "slot-a" else "slot-a"


@dataclass(frozen=True, slots=True, kw_only=True)
class SlotRuntime:
    """State of one component slot copy."""

    slot_id: SlotId
    release_id: str | None
    image_digest: str | None
    running: bool
    healthy: bool
    write_authority: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class DualSlotState:
    """Two-slot state for a lifecycle agent, infrastructure agent, or Target Hub."""

    component: SelfUpgradeComponent
    active_slot: SlotId
    fencing_generation: int
    slots: dict[SlotId, SlotRuntime]

    def __post_init__(self) -> None:
        if self.component not in _SUPPORTED_COMPONENTS:
            raise ValueError("component is unsupported")
        if self.active_slot not in ("slot-a", "slot-b"):
            raise ValueError("active_slot is invalid")
        if (
            isinstance(self.fencing_generation, bool)
            or not isinstance(self.fencing_generation, int)
            or self.fencing_generation < 1
        ):
            raise ValueError("fencing_generation MUST be a positive integer")
        if set(self.slots) != {"slot-a", "slot-b"}:
            raise ValueError("slots MUST contain slot-a and slot-b")
        writers = [slot_id for slot_id, s in self.slots.items() if s.write_authority]
        if writers != [self.active_slot]:
            raise ValueError("exactly the active slot MUST hold write_authority")

    @classmethod
    def initial(
        cls,
        *,
        component: SelfUpgradeComponent,
        release_id: str,
        image_digest: str,
        active_slot: SlotId = "slot-a",
        fencing_generation: int = 1,
    ) -> DualSlotState:
        if not is_release_id(release_id):
            raise ValueError("release_id MUST be canonical SemVer")
        if _IMAGE_DIGEST.fullmatch(image_digest) is None:
            raise ValueError("image_digest MUST be sha256:<64 hex>")
        standby = _other_slot(active_slot)
        return cls(
            component=component,
            active_slot=active_slot,
            fencing_generation=fencing_generation,
            slots={
                active_slot: SlotRuntime(
                    slot_id=active_slot,
                    release_id=release_id,
                    image_digest=image_digest,
                    running=True,
                    healthy=True,
                    write_authority=True,
                ),
                standby: SlotRuntime(
                    slot_id=standby,
                    release_id=None,
                    image_digest=None,
                    running=False,
                    healthy=False,
                    write_authority=False,
                ),
            },
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SelfUpgradeResult:
    """Result of one dual-slot self-upgrade attempt."""

    outcome: SelfUpgradeOutcome
    reason_code: str
    state: DualSlotState


class DualSlotUpgradeController:
    """Start candidate without write authority, verify health, and cut over or roll back."""

    def upgrade(
        self,
        state: DualSlotState,
        *,
        target_release_id: str,
        target_image_digest: str,
        check_candidate_health: Callable[[SelfUpgradeComponent, SlotId, str, str], bool],
        verify_post_handoff_readback: Callable[[SelfUpgradeComponent, SlotId, int], bool]
        | None = None,
    ) -> SelfUpgradeResult:
        if not is_release_id(target_release_id):
            raise ValueError("target_release_id MUST be canonical SemVer")
        if _IMAGE_DIGEST.fullmatch(target_image_digest) is None:
            raise ValueError("target_image_digest MUST be sha256:<64 hex>")

        old_slot_id = state.active_slot
        candidate_slot_id = _other_slot(old_slot_id)
        old_slot = state.slots[old_slot_id]

        # 1. Candidate starts beside the old slot with write_authority=False.
        candidate_healthy = bool(
            check_candidate_health(
                state.component,
                candidate_slot_id,
                target_release_id,
                target_image_digest,
            )
        )
        if not candidate_healthy:
            rolled_back_slots = {
                old_slot_id: old_slot,
                candidate_slot_id: SlotRuntime(
                    slot_id=candidate_slot_id,
                    release_id=target_release_id,
                    image_digest=target_image_digest,
                    running=False,
                    healthy=False,
                    write_authority=False,
                ),
            }
            return SelfUpgradeResult(
                outcome="rolled-back",
                reason_code="candidate_health_check_failed",
                state=replace(state, slots=rolled_back_slots),
            )

        next_generation = state.fencing_generation + 1
        if verify_post_handoff_readback is not None and not bool(
            verify_post_handoff_readback(state.component, candidate_slot_id, next_generation)
        ):
            rolled_back_slots = {
                old_slot_id: old_slot,
                candidate_slot_id: SlotRuntime(
                    slot_id=candidate_slot_id,
                    release_id=target_release_id,
                    image_digest=target_image_digest,
                    running=False,
                    healthy=False,
                    write_authority=False,
                ),
            }
            return SelfUpgradeResult(
                outcome="rolled-back",
                reason_code="post_handoff_readback_failed",
                state=replace(state, slots=rolled_back_slots),
            )

        # 2. Transfer fenced write authority to the healthy candidate; keep old slot as rollback target.
        upgraded_slots = {
            old_slot_id: replace(old_slot, write_authority=False),
            candidate_slot_id: SlotRuntime(
                slot_id=candidate_slot_id,
                release_id=target_release_id,
                image_digest=target_image_digest,
                running=True,
                healthy=True,
                write_authority=True,
            ),
        }
        return SelfUpgradeResult(
            outcome="upgraded",
            reason_code="upgraded",
            state=DualSlotState(
                component=state.component,
                active_slot=candidate_slot_id,
                fencing_generation=next_generation,
                slots=upgraded_slots,
            ),
        )

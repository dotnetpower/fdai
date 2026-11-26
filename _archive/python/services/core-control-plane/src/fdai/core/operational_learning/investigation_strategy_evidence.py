"""Transport-safe evidence for Norns-owned investigation strategy learning."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from fdai.core.rca.discrimination_shadow import (
    ChallengerComparisonOutcome,
    DiscriminationShadowComparison,
    ShadowComparisonDisposition,
    discrimination_shadow_material,
)


@dataclass(frozen=True, slots=True)
class InvestigationStrategyComparisonEvidence:
    """Bounded comparison summary that grants no learning or activation authority."""

    comparison_id: str
    comparison_digest: str
    active_strategy_digest: str
    challenger_strategy_digest: str
    disposition: ShadowComparisonDisposition
    challenger_outcome: ChallengerComparisonOutcome | None
    agreement: bool
    realized_evidence_eligible: bool
    safety_failure: bool
    invariant_failure: bool
    comparison_material_json: str
    execution_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    def __post_init__(self) -> None:
        _text("comparison_id", self.comparison_id)
        for digest_name, digest_value in (
            ("comparison_digest", self.comparison_digest),
            ("active_strategy_digest", self.active_strategy_digest),
            ("challenger_strategy_digest", self.challenger_strategy_digest),
        ):
            _digest(digest_name, digest_value)
        if self.active_strategy_digest == self.challenger_strategy_digest:
            raise ValueError("investigation strategy evidence requires distinct strategies")
        if not isinstance(self.disposition, ShadowComparisonDisposition):
            raise ValueError("investigation strategy evidence disposition is invalid")
        if self.challenger_outcome is not None and not isinstance(
            self.challenger_outcome,
            ChallengerComparisonOutcome,
        ):
            raise ValueError("investigation strategy challenger outcome is invalid")
        for flag_name, flag_value in (
            ("agreement", self.agreement),
            ("realized_evidence_eligible", self.realized_evidence_eligible),
            ("safety_failure", self.safety_failure),
            ("invariant_failure", self.invariant_failure),
        ):
            if not isinstance(flag_value, bool):
                raise ValueError(f"{flag_name} MUST be boolean")
        if self.execution_authority is not False or self.promotion_authority is not False:
            raise ValueError("investigation strategy evidence MUST NOT grant authority")
        try:
            material = json.loads(self.comparison_material_json)
        except json.JSONDecodeError as exc:
            raise ValueError("comparison material MUST be canonical JSON") from exc
        canonical = json.dumps(
            material,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        if canonical != self.comparison_material_json:
            raise ValueError("comparison material MUST be canonical JSON")
        expected_digest = f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"
        if expected_digest != self.comparison_digest:
            raise ValueError("comparison evidence digest does not match its material")
        expected_id = f"discrimination-shadow-{expected_digest[7:39]}"
        if self.comparison_id != expected_id:
            raise ValueError("comparison evidence id does not match its digest")
        expected = {
            "active_strategy_digest": self.active_strategy_digest,
            "challenger_strategy_digest": self.challenger_strategy_digest,
            "disposition": self.disposition.value,
            "challenger_outcome": (
                self.challenger_outcome.value if self.challenger_outcome is not None else None
            ),
            "agreement": self.agreement,
            "realized_evidence_eligible": self.realized_evidence_eligible,
            "safety_failure": self.safety_failure,
            "invariant_failure": self.invariant_failure,
        }
        if any(material.get(key) != value for key, value in expected.items()):
            raise ValueError("comparison evidence summary does not match its material")

    @classmethod
    def from_shadow(
        cls,
        comparison: DiscriminationShadowComparison,
    ) -> InvestigationStrategyComparisonEvidence:
        """Project one in-process comparison into its transport-safe evidence."""

        material = discrimination_shadow_material(comparison)
        material_json = json.dumps(
            material,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return cls(
            comparison_id=comparison.comparison_id,
            comparison_digest=comparison.comparison_digest,
            active_strategy_digest=comparison.active_strategy_digest,
            challenger_strategy_digest=comparison.challenger_strategy_digest,
            disposition=comparison.disposition,
            challenger_outcome=comparison.challenger_outcome,
            agreement=comparison.agreement,
            realized_evidence_eligible=comparison.realized_evidence_eligible,
            safety_failure=comparison.safety_failure,
            invariant_failure=comparison.invariant_failure,
            comparison_material_json=material_json,
        )

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
    ) -> InvestigationStrategyComparisonEvidence:
        """Validate one Muninn transport record without filling missing fields."""

        allowed = {
            "comparison_id",
            "comparison_digest",
            "active_strategy_digest",
            "challenger_strategy_digest",
            "disposition",
            "challenger_outcome",
            "agreement",
            "realized_evidence_eligible",
            "safety_failure",
            "invariant_failure",
            "comparison_material_json",
            "execution_authority",
            "promotion_authority",
        }
        if set(value) != allowed:
            raise ValueError("investigation strategy evidence fields do not match the contract")
        outcome = value["challenger_outcome"]
        return cls(
            comparison_id=str(value["comparison_id"]),
            comparison_digest=str(value["comparison_digest"]),
            active_strategy_digest=str(value["active_strategy_digest"]),
            challenger_strategy_digest=str(value["challenger_strategy_digest"]),
            disposition=ShadowComparisonDisposition(str(value["disposition"])),
            challenger_outcome=(
                ChallengerComparisonOutcome(str(outcome)) if outcome is not None else None
            ),
            agreement=_boolean(value["agreement"], "agreement"),
            realized_evidence_eligible=_boolean(
                value["realized_evidence_eligible"],
                "realized_evidence_eligible",
            ),
            safety_failure=_boolean(value["safety_failure"], "safety_failure"),
            invariant_failure=_boolean(
                value["invariant_failure"],
                "invariant_failure",
            ),
            comparison_material_json=str(value["comparison_material_json"]),
            execution_authority=_false(
                value["execution_authority"],
                "execution_authority",
            ),
            promotion_authority=_false(
                value["promotion_authority"],
                "promotion_authority",
            ),
        )

    def to_mapping(self) -> dict[str, object]:
        """Return the exact bounded mapping accepted by Norns."""

        return {
            "comparison_id": self.comparison_id,
            "comparison_digest": self.comparison_digest,
            "active_strategy_digest": self.active_strategy_digest,
            "challenger_strategy_digest": self.challenger_strategy_digest,
            "disposition": self.disposition.value,
            "challenger_outcome": (
                self.challenger_outcome.value if self.challenger_outcome is not None else None
            ),
            "agreement": self.agreement,
            "realized_evidence_eligible": self.realized_evidence_eligible,
            "safety_failure": self.safety_failure,
            "invariant_failure": self.invariant_failure,
            "comparison_material_json": self.comparison_material_json,
            "execution_authority": False,
            "promotion_authority": False,
        }


def _text(name: str, value: str) -> None:
    if not value or len(value) > 256:
        raise ValueError(f"{name} MUST be non-empty and bounded")


def _digest(name: str, value: str) -> None:
    if (
        len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"{name} MUST be a SHA-256 digest")


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} MUST be boolean")
    return value


def _false(value: object, name: str) -> Literal[False]:
    if value is not False:
        raise ValueError(f"{name} MUST be false")
    return False


__all__ = ["InvestigationStrategyComparisonEvidence"]

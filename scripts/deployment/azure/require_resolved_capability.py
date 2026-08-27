#!/usr/bin/env python3
"""Require one exact resolved model capability before protected planning."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fdai.rule_catalog.schema.llm_resolver import CapabilityStatus, ResolvedModels
from fdai.rule_catalog.schema.model_endpoint import (
    ModelCapacityUnit,
    ModelProviderKind,
)


class CapabilityRequirementError(ValueError):
    """Raised when a protected model capability requirement is not satisfied."""


def chatops_validation_required(metadata: object, *, requested: bool) -> bool:
    """Match the apply request to the validation mode sealed during planning."""
    if not isinstance(metadata, dict):
        raise CapabilityRequirementError("protected plan metadata must be an object")
    resolution = metadata.get("model_resolution")
    sealed = False
    if resolution is not None:
        if not isinstance(resolution, dict):
            raise CapabilityRequirementError("protected model resolution metadata is invalid")
        sealed = resolution.get("chatops_channel_validation", False)
        if not isinstance(sealed, bool):
            raise CapabilityRequirementError("protected ChatOps validation flag is invalid")
    if sealed != requested:
        raise CapabilityRequirementError(
            "ChatOps validation input does not match the protected plan"
        )
    return sealed


def require_resolved_capability(
    resolved: ResolvedModels,
    *,
    capability: str,
    publisher: str,
    family: str,
    version: str,
    sku: str,
    minimum_capacity_tpm: int,
    provider_kind: ModelProviderKind,
    endpoint_ref: str,
) -> None:
    """Reject any missing, degraded, mismatched, or unbound capability."""
    if minimum_capacity_tpm < 1:
        raise CapabilityRequirementError("minimum capacity must be positive")
    matches = [item for item in resolved.capabilities if item.name == capability]
    if len(matches) != 1:
        raise CapabilityRequirementError("required model capability must appear exactly once")
    selected = matches[0]
    if selected.status not in {
        CapabilityStatus.RESOLVED,
        CapabilityStatus.CAPACITY_REDUCED,
    }:
        raise CapabilityRequirementError("required model capability is not resolved")
    if (
        selected.publisher != publisher
        or selected.family != family
        or selected.version != version
        or selected.sku != sku
        or selected.capacity_unit != "tpm"
        or selected.capacity_tpm < minimum_capacity_tpm
    ):
        raise CapabilityRequirementError(
            "required model capability does not match the approved profile"
        )

    bindings = [item for item in resolved.endpoint_bindings if item.capability == capability]
    if len(bindings) != 1:
        raise CapabilityRequirementError("required model capability must have one endpoint binding")
    binding = bindings[0]
    if (
        binding.provider_kind is not provider_kind
        or binding.endpoint_ref != endpoint_ref
        or endpoint_ref.split(":", 1)[0] != provider_kind.value
        or binding.deployment != capability
        or binding.publisher != publisher
        or binding.family != family
        or binding.version != version
        or binding.capacity.unit is not ModelCapacityUnit.TPM
        or binding.capacity.value < minimum_capacity_tpm
    ):
        raise CapabilityRequirementError(
            "required model endpoint binding does not match the profile"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolved", type=Path, required=True)
    parser.add_argument("--endpoint-ref", required=True)
    parser.add_argument("--plan-metadata", type=Path)
    parser.add_argument("--requested-validation", choices=("true", "false"))
    args = parser.parse_args()
    try:
        if args.plan_metadata is not None:
            if args.requested_validation is None:
                raise CapabilityRequirementError(
                    "--requested-validation is required with --plan-metadata"
                )
            metadata = json.loads(args.plan_metadata.read_text(encoding="utf-8"))
            if not chatops_validation_required(
                metadata,
                requested=args.requested_validation == "true",
            ):
                return 0
        resolved = ResolvedModels.from_json(args.resolved.read_text(encoding="utf-8"))
        require_resolved_capability(
            resolved,
            capability="t2.reasoner.secondary",
            publisher="MistralAI",
            family="Mistral-Large-3",
            version="1",
            sku="GlobalStandard",
            minimum_capacity_tpm=1_000,
            provider_kind=ModelProviderKind.AZURE_FOUNDRY,
            endpoint_ref=args.endpoint_ref,
        )
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

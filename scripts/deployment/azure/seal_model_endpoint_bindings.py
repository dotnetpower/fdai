#!/usr/bin/env python3
"""Add deterministic Azure Foundry endpoint bindings to resolved models."""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from fdai.rule_catalog.schema.llm_resolver import CapabilityStatus, ResolvedModels
from fdai.rule_catalog.schema.model_endpoint import (
    ModelApiStyle,
    ModelAuthKind,
    ModelCapacityUnit,
    ModelDiscoverySource,
    ModelEndpointBinding,
    ModelEndpointCapacity,
    ModelEndpointDiscovery,
    ModelEndpointFeatures,
    ModelProviderKind,
    ModelRouteKind,
)

_PARTNER_PUBLISHERS = frozenset({"Anthropic", "MistralAI"})


def seal_partner_bindings(
    resolved: ResolvedModels,
    *,
    partner_account_name: str,
    verified_at: datetime,
) -> ResolvedModels:
    """Bind resolved partner capabilities to one deployment-owned account ref."""

    if verified_at.tzinfo is None or verified_at.utcoffset() is None:
        raise ValueError("verified_at MUST be timezone-aware")
    endpoint_ref = f"azure-foundry:{partner_account_name}"
    existing = {binding.capability: binding for binding in resolved.endpoint_bindings}
    additions: list[ModelEndpointBinding] = []
    for capability in resolved.capabilities:
        if capability.publisher not in _PARTNER_PUBLISHERS:
            continue
        if capability.status not in {
            CapabilityStatus.RESOLVED,
            CapabilityStatus.CAPACITY_REDUCED,
        }:
            continue
        if capability.name in existing:
            raise ValueError("partner capability already has an endpoint binding")
        if (
            capability.family is None
            or capability.version is None
            or capability.capacity_unit != "tpm"
            or capability.capacity_tpm < 1000
        ):
            raise ValueError("resolved partner capability is not deployable")
        additions.append(
            ModelEndpointBinding(
                binding_id=f"foundry-direct:{capability.name}",
                capability=capability.name,
                provider_kind=ModelProviderKind.AZURE_FOUNDRY,
                route_kind=ModelRouteKind.DIRECT,
                api_style=ModelApiStyle.OPENAI_V1,
                endpoint_ref=endpoint_ref,
                deployment=capability.name,
                auth_kind=ModelAuthKind.ENTRA,
                auth_audience="https://cognitiveservices.azure.com/.default",
                publisher=capability.publisher,
                family=capability.family,
                version=capability.version,
                capacity=ModelEndpointCapacity(
                    unit=ModelCapacityUnit.TPM,
                    value=capability.capacity_tpm,
                ),
                features=ModelEndpointFeatures(
                    streaming=True,
                    structured_output=True,
                ),
                discovery=ModelEndpointDiscovery(
                    source=ModelDiscoverySource.AZURE_MANAGEMENT,
                    resource_ref_digest=hashlib.sha256(endpoint_ref.encode()).hexdigest(),
                    verified_at=verified_at,
                ),
            )
        )
    return replace(
        resolved,
        endpoint_bindings=tuple(
            sorted((*resolved.endpoint_bindings, *additions), key=lambda item: item.capability)
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--partner-account-name", required=True)
    parser.add_argument("--verified-at", required=True)
    args = parser.parse_args()
    resolved = ResolvedModels.from_json(args.input.read_text(encoding="utf-8"))
    sealed = seal_partner_bindings(
        resolved,
        partner_account_name=args.partner_account_name,
        verified_at=datetime.fromisoformat(args.verified_at.replace("Z", "+00:00")),
    )
    args.output.write_text(sealed.to_json() + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

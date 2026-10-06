"""Runtime composition for the selected policy-administration add-on."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import httpx
from fdai_service_contracts.policy_administration import (
    PolicyMode,
    ReleaseCapabilityMaximums,
)
from fdai_service_contracts.product_profile import ProductAddOn, ProductProfile

from fdai.agents import (
    POLICY_ADMIN_OPA_CAPABILITIES_RELATIVE,
    MimirPolicyAdministration,
    OpaRegoPolicyCompiler,
    OperatorRequestReceiptGate,
    StateStorePolicyRevisionStore,
)
from fdai.delivery.policy_signing import (
    DEFAULT_POLICY_SIGNING_ALGORITHM,
    AzureKeyVaultPolicyRevisionSigner,
)
from fdai.delivery.repo_assets import repo_asset_root
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity

POLICY_ADMIN_KEY_VAULT_KEY_ID_ENV = "FDAI_POLICY_ADMIN_KEY_VAULT_KEY_ID"
POLICY_ADMIN_KEY_VAULT_CLIENT_ID_ENV = "FDAI_POLICY_ADMIN_KEY_VAULT_MI_CLIENT_ID"
POLICY_ADMIN_KEY_VAULT_ALGORITHM_ENV = "FDAI_POLICY_ADMIN_KEY_VAULT_ALGORITHM"
POLICY_ADMIN_OPA_BINARY_ENV = "FDAI_POLICY_ADMIN_OPA_BINARY"
POLICY_ADMIN_OPERATOR_PRODUCER_ID_ENV = "FDAI_OPERATOR_REQUEST_OPERATOR_PRODUCER_ID"


@dataclass(frozen=True, slots=True)
class FailClosedReleaseMaximums:
    """Interim Release-maximum source until #1822 supplies signed Release data."""

    def maximum_mode_for_action_type(self, action_type: str) -> PolicyMode | None:
        del action_type
        return PolicyMode.SHADOW


def policy_administration_selected(profile: ProductProfile) -> bool:
    """Return whether the explicit add-on selected the Mimir policy port."""

    return profile.selects(ProductAddOn.POLICY_ADMINISTRATION)


def build_mimir_policy_administration(
    *,
    environment: Mapping[str, str],
    state_store: StateStore,
    http_client: httpx.AsyncClient | None,
    workload_identity_builder: Callable[..., WorkloadIdentity],
    operator_request_receipt_gate: OperatorRequestReceiptGate | None,
    clock: object | None = None,
    asset_root: Path | None = None,
    release_maximums: ReleaseCapabilityMaximums | None = None,
) -> MimirPolicyAdministration:
    """Bind Mimir's policy-admin port or fail closed before runtime starts."""

    if operator_request_receipt_gate is None:
        raise RuntimeError("policy administration requires Operator request receipt verification")
    key_id = environment.get(POLICY_ADMIN_KEY_VAULT_KEY_ID_ENV, "").strip()
    if not key_id:
        raise RuntimeError(f"{POLICY_ADMIN_KEY_VAULT_KEY_ID_ENV} is required")
    if http_client is None:
        raise RuntimeError("policy administration Key Vault signing requires an HTTP client")
    identity = workload_identity_builder(
        http_client,
        client_id_env=POLICY_ADMIN_KEY_VAULT_CLIENT_ID_ENV,
        require_client_id=True,
    )
    opa_binary = environment.get(POLICY_ADMIN_OPA_BINARY_ENV, "").strip() or "opa"
    capabilities_file = (asset_root or repo_asset_root()) / POLICY_ADMIN_OPA_CAPABILITIES_RELATIVE
    algorithm = (
        environment.get(POLICY_ADMIN_KEY_VAULT_ALGORITHM_ENV, "").strip()
        or DEFAULT_POLICY_SIGNING_ALGORITHM
    )
    producer_id = (
        environment.get(POLICY_ADMIN_OPERATOR_PRODUCER_ID_ENV, "").strip() or "operator-service"
    )
    return MimirPolicyAdministration(
        store=StateStorePolicyRevisionStore(state_store),
        signer=AzureKeyVaultPolicyRevisionSigner(
            key_id=key_id,
            identity=identity,
            http_client=http_client,
            algorithm=algorithm,
        ),
        rego_compiler=OpaRegoPolicyCompiler(
            opa_binary=opa_binary,
            capabilities_file=capabilities_file,
        ),
        operator_request_receipt_gate=operator_request_receipt_gate,
        operator_producer_service_identity=producer_id,
        release_maximums=release_maximums or FailClosedReleaseMaximums(),
        clock=clock,
    )


__all__ = [
    "POLICY_ADMIN_KEY_VAULT_ALGORITHM_ENV",
    "POLICY_ADMIN_KEY_VAULT_CLIENT_ID_ENV",
    "POLICY_ADMIN_KEY_VAULT_KEY_ID_ENV",
    "POLICY_ADMIN_OPERATOR_PRODUCER_ID_ENV",
    "POLICY_ADMIN_OPA_BINARY_ENV",
    "FailClosedReleaseMaximums",
    "build_mimir_policy_administration",
    "policy_administration_selected",
]

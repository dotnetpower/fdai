from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fdai.agents import OperatorRequestReceiptGate, StateStorePolicyRevisionStore
from fdai.runtime import policy_administration as composition
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai.shared.providers.workload_identity import IdentityToken
from fdai_service_contracts.policy_administration import PolicyMode
from fdai_service_contracts.product_profile import ProductAddOn, ProductProfile


class _Verifier:
    def verify_operator_request_receipt(self, *, receipt: object, signing_bytes: bytes) -> bool:
        return bool(receipt and signing_bytes)


@dataclass
class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="token",
            audience=audience,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )


class _Http:
    pass


class _Rego:
    def __init__(self, *, opa_binary: str, capabilities_file: Path | None) -> None:
        self.opa_binary = opa_binary
        self.capabilities_file = capabilities_file

    async def compile(self, rego: str) -> None:
        del rego

    async def test(self, rego: str, tests: tuple[dict[str, object], ...]) -> None:
        del rego, tests


class _Signer:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    async def sign_policy_revision(self, *, policy_digest: str, revision_id: str) -> str:
        return f"signature:{revision_id}:{policy_digest}"


def _gate() -> OperatorRequestReceiptGate:
    return OperatorRequestReceiptGate(
        verifier=_Verifier(),
        state_store=InMemoryStateStore(),
        clock=lambda: datetime.now(UTC),
    )


def _identity_builder(*args: object, **kwargs: object) -> _Identity:
    assert args and isinstance(args[0], _Http)
    assert kwargs["client_id_env"] == composition.POLICY_ADMIN_KEY_VAULT_CLIENT_ID_ENV
    assert kwargs["require_client_id"] is True
    return _Identity()


def test_policy_administration_selection_is_explicit() -> None:
    assert not composition.policy_administration_selected(ProductProfile())
    assert composition.policy_administration_selected(
        ProductProfile(
            add_ons=(
                ProductAddOn.ENTERPRISE_IDENTITY_GOVERNANCE,
                ProductAddOn.POLICY_ADMINISTRATION,
                ProductAddOn.READ_ONLY_CONSOLE,
            )
        )
    )


def test_build_mimir_policy_administration_binds_required_ports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(composition, "OpaRegoPolicyCompiler", _Rego)
    monkeypatch.setattr(composition, "AzureKeyVaultPolicyRevisionSigner", _Signer)
    asset_root = tmp_path
    capabilities = asset_root / "rule-catalog/schema/policy_admin_opa_capabilities.json"
    capabilities.parent.mkdir(parents=True)
    capabilities.write_text("{}", encoding="utf-8")

    admin = composition.build_mimir_policy_administration(
        environment={
            composition.POLICY_ADMIN_KEY_VAULT_KEY_ID_ENV: (
                "https://fdai-example.vault.azure.net/keys/policy-signing"
            ),
            composition.POLICY_ADMIN_OPA_BINARY_ENV: "opa-test",
        },
        state_store=InMemoryStateStore(),
        http_client=_Http(),  # type: ignore[arg-type]
        workload_identity_builder=_identity_builder,
        operator_request_receipt_gate=_gate(),
        asset_root=asset_root,
    )

    assert isinstance(admin.store, StateStorePolicyRevisionStore)
    assert isinstance(admin.rego_compiler, _Rego)
    assert admin.rego_compiler.opa_binary == "opa-test"
    assert admin.rego_compiler.capabilities_file == capabilities
    assert admin.release_maximums is not None
    assert admin.release_maximums.maximum_mode_for_action_type("governance.retire-rule") is (
        PolicyMode.SHADOW
    )


@pytest.mark.parametrize(
    ("environment", "http_client", "gate", "message"),
    [
        ({}, _Http(), _gate(), "KEY_VAULT_KEY_ID"),
        (
            {
                composition.POLICY_ADMIN_KEY_VAULT_KEY_ID_ENV: (
                    "https://fdai-example.vault.azure.net/keys/policy-signing"
                )
            },
            None,
            _gate(),
            "HTTP client",
        ),
        (
            {
                composition.POLICY_ADMIN_KEY_VAULT_KEY_ID_ENV: (
                    "https://fdai-example.vault.azure.net/keys/policy-signing"
                )
            },
            _Http(),
            None,
            "receipt verification",
        ),
    ],
)
def test_build_mimir_policy_administration_fails_closed_when_dependency_missing(
    environment: dict[str, str],
    http_client: _Http | None,
    gate: OperatorRequestReceiptGate | None,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(composition, "OpaRegoPolicyCompiler", _Rego)
    monkeypatch.setattr(composition, "AzureKeyVaultPolicyRevisionSigner", _Signer)

    with pytest.raises(RuntimeError, match=message):
        composition.build_mimir_policy_administration(
            environment=environment,
            state_store=InMemoryStateStore(),
            http_client=http_client,  # type: ignore[arg-type]
            workload_identity_builder=_identity_builder,
            operator_request_receipt_gate=gate,
        )

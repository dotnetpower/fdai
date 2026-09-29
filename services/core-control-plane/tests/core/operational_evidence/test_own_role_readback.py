"""Verifier own-role readback fails closed on unexpected role assignments."""

from __future__ import annotations

from fdai.core.operational_evidence.own_role_readback import (
    OwnRolePolicy,
    VerifierOwnRoleReadback,
    VerifierRoleAssignment,
    evaluate_verifier_own_roles,
)

_OTHER = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-other"
_REGISTRY = _OTHER + "/providers/Microsoft.ContainerRegistry/registries/fdai"
_DSN_SECRET = _OTHER + "/providers/Microsoft.KeyVault/vaults/fdai/secrets/verifier-dsn"
_STATE_SECRET = _OTHER + "/providers/Microsoft.KeyVault/vaults/fdai/secrets/state-store-dsn"
_VAULT = _OTHER + "/providers/Microsoft.KeyVault/vaults/fdai"


def _readback(
    assignments: tuple[VerifierRoleAssignment, ...],
    *,
    complete: bool = True,
    principal_id: str = "verifier-principal",
) -> VerifierOwnRoleReadback:
    return VerifierOwnRoleReadback(
        principal_id=principal_id,
        assignments=assignments,
        complete=complete,
        observed_scopes=(_OTHER,),
    )


def test_own_role_readback_allows_exact_rendered_read_roles_only() -> None:
    reasons = evaluate_verifier_own_roles(
        _readback(
            (
                VerifierRoleAssignment(_OTHER, "reader", "Reader", actions=("*/read",)),
                VerifierRoleAssignment(
                    _DSN_SECRET,
                    "kv-secrets",
                    "Key Vault Secrets User",
                    actions=("Microsoft.KeyVault/vaults/secrets/getSecret/action",),
                ),
                VerifierRoleAssignment(
                    _OTHER,
                    "monitoring-reader",
                    "Monitoring Reader",
                    actions=("Microsoft.OperationalInsights/workspaces/search/action", "*/read"),
                ),
                VerifierRoleAssignment(
                    _REGISTRY,
                    "acr-pull",
                    "AcrPull",
                    data_actions=("Microsoft.ContainerRegistry/registries/pull/read",),
                ),
            )
        ),
        policy=OwnRolePolicy(
            verifier_principal_id="verifier-principal",
            allowed_role_scopes={
                "AcrPull": (_REGISTRY,),
                "Key Vault Secrets User": (_DSN_SECRET,),
                "Monitoring Reader": (_OTHER,),
                "Reader": (_OTHER,),
            },
        ),
    )
    assert reasons == ()


def test_own_role_readback_blocks_forbidden_partial_and_unavailable_reads() -> None:
    policy = OwnRolePolicy(
        verifier_principal_id="verifier-principal",
        allowed_role_scopes={
            "AcrPull": (_REGISTRY,),
            "Key Vault Secrets User": (_DSN_SECRET,),
            "Monitoring Reader": (_OTHER,),
            "Reader": (_OTHER,),
        },
    )
    forbidden = evaluate_verifier_own_roles(
        _readback((VerifierRoleAssignment(_OTHER, "contributor", "Contributor", actions=("*",)),)),
        policy=policy,
    )
    assert forbidden == ("role_scope_not_allowed",)
    data_plane = evaluate_verifier_own_roles(
        _readback(
            (
                VerifierRoleAssignment(
                    _OTHER,
                    "blob-reader",
                    "Storage Blob Data Reader",
                    data_actions=(
                        "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read",
                    ),
                ),
            )
        ),
        policy=policy,
    )
    assert data_plane == ("role_scope_not_allowed",)
    storage_writer = evaluate_verifier_own_roles(
        _readback(
            (
                VerifierRoleAssignment(
                    _OTHER,
                    "blob-contrib",
                    "Storage Blob Data Contributor",
                    data_actions=(
                        "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write",
                    ),
                ),
            )
        ),
        policy=policy,
    )
    assert storage_writer == ("role_scope_not_allowed",)
    for scope in (_VAULT, _OTHER, _STATE_SECRET):
        reasons = evaluate_verifier_own_roles(
            _readback(
                (
                    VerifierRoleAssignment(
                        scope,
                        "kv-secrets",
                        "Key Vault Secrets User",
                        actions=("Microsoft.KeyVault/vaults/secrets/getSecret/action",),
                    ),
                )
            ),
            policy=policy,
        )
        assert reasons == ("role_scope_not_allowed",)
    partial = evaluate_verifier_own_roles(_readback((), complete=False), policy=policy)
    assert partial == ("role_readback_partial",)
    unavailable = evaluate_verifier_own_roles(
        VerifierOwnRoleReadback(
            principal_id="verifier-principal",
            assignments=(),
            complete=True,
            observed_scopes=(),
        ),
        policy=policy,
    )
    assert unavailable == ("role_readback_unavailable",)


def test_own_role_readback_refuses_unresolved_definition_and_identity_mismatch() -> None:
    policy = OwnRolePolicy(
        verifier_principal_id="verifier-principal",
        allowed_role_scopes={"Reader": (_OTHER,)},
    )
    unresolved = evaluate_verifier_own_roles(
        _readback((VerifierRoleAssignment(_OTHER, "unknown", ""),)),
        policy=policy,
    )
    assert unresolved == ("role_definition_unresolved",)
    mismatch = evaluate_verifier_own_roles(
        _readback(
            (VerifierRoleAssignment(_OTHER, "reader", "Reader", actions=("*/read",)),),
            principal_id="other",
        ),
        policy=policy,
    )
    assert mismatch == ("role_readback_principal_mismatch",)

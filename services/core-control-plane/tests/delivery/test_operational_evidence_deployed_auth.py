"""Deployed operational-evidence caller authentication and startup wiring."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fdai.core.operational_evidence.own_role_readback import (
    VerifierOwnRoleReadback,
    VerifierRoleAssignment,
)
from fdai.core.operational_evidence.separation import ProofStoreGrantReadback
from fdai.delivery import operational_evidence_server
from fdai.delivery.operational_evidence_caller_auth import (
    BearerTokenValidator,
    CallerAuthenticationError,
    StaticJwksBearerTokenValidator,
    ValidatedCallerToken,
    WorkloadCallerAuthenticator,
)
from fdai.delivery.operational_evidence_server import build_verifier_workload
from fdai_service_contracts.operational_evidence import OperationalEvidenceSourceHealth

from tests.core.operational_evidence.support import anchors_json
from tests.delivery.test_operational_evidence_venue import _workload_env

_RG = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-fdai"
_REGISTRY = _RG + "/providers/Microsoft.ContainerRegistry/registries/fdai"
_DSN_SECRET = _RG + "/providers/Microsoft.KeyVault/vaults/fdai/secrets/verifier-dsn"


@dataclass(frozen=True, slots=True)
class _TokenValidator(BearerTokenValidator):
    claims: ValidatedCallerToken

    def validate(self, token: str) -> ValidatedCallerToken:
        if token != "signed-token":
            raise CallerAuthenticationError("invalid token")
        return self.claims


def _request(value: str) -> object:
    return SimpleNamespace(headers={"Authorization": value})


def _jwt_fixture(
    *,
    issuer: str,
    audience: str,
    kid: str = "kid-one",
    exp_delta: int = 300,
) -> tuple[str, str, rsa.RSAPrivateKey]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    jwk.update(kid=kid, use="sig", alg="RS256")
    token = jwt.encode(
        {
            "iss": issuer,
            "aud": audience,
            "oid": "producer-principal",
            "exp": int(datetime.now(UTC).timestamp()) + exp_delta,
        },
        key,
        algorithm="RS256",
        headers={"kid": kid},
    )
    return token, json.dumps({"keys": [jwk]}, sort_keys=True), key


def test_workload_authenticator_accepts_only_registered_producer_oid() -> None:
    future = int((datetime.now(UTC) + timedelta(minutes=5)).timestamp())
    authenticator = WorkloadCallerAuthenticator(
        expected_issuer="https://login.example.invalid/tenant/v2.0",
        expected_audience="api://fdai-operational-evidence-verifier",
        registered_producer_principal="producer-principal",
        validator=_TokenValidator(
            ValidatedCallerToken(
                issuer="https://login.example.invalid/tenant/v2.0",
                audience="api://fdai-operational-evidence-verifier",
                oid="producer-principal",
                expires_at=future,
            )
        ),
    )
    assert authenticator.authenticate(_request("Bearer signed-token")) == "producer-principal"
    assert authenticator.authenticate(_request("Bearer wrong")) is None
    assert authenticator.authenticate(_request("Basic signed-token")) is None
    wrong_oid = WorkloadCallerAuthenticator(
        expected_issuer=authenticator.expected_issuer,
        expected_audience=authenticator.expected_audience,
        registered_producer_principal="other-principal",
        validator=authenticator.validator,
    )
    assert wrong_oid.authenticate(_request("Bearer signed-token")) is None


def test_static_jwks_validator_accepts_valid_token_and_refuses_invalid_cases() -> None:
    issuer = "https://login.example.invalid/tenant/v2.0"
    audience = "api://fdai-operational-evidence-verifier"
    token, jwks, key = _jwt_fixture(issuer=issuer, audience=audience)
    validator = StaticJwksBearerTokenValidator(issuer=issuer, audience=audience, jwks_json=jwks)
    assert validator.validate(token).oid == "producer-principal"
    unknown_kid = jwt.encode(
        {
            "iss": issuer,
            "aud": audience,
            "oid": "producer-principal",
            "exp": int(datetime.now(UTC).timestamp()) + 300,
        },
        key,
        algorithm="RS256",
        headers={"kid": "unknown"},
    )
    for kwargs in (
        {"issuer": "https://issuer.example.invalid", "audience": audience},
        {"issuer": issuer, "audience": "api://wrong"},
    ):
        with pytest.raises(CallerAuthenticationError, match="invalid"):
            StaticJwksBearerTokenValidator(jwks_json=jwks, **kwargs).validate(token)
    expired, expired_jwks, _ = _jwt_fixture(issuer=issuer, audience=audience, exp_delta=-10)
    for candidate, source in (
        (unknown_kid, jwks),
        (expired, expired_jwks),
        ("not-a-token", jwks),
    ):
        with pytest.raises(CallerAuthenticationError) as exc:
            StaticJwksBearerTokenValidator(
                issuer=issuer, audience=audience, jwks_json=source
            ).validate(candidate)
        assert candidate not in str(exc.value)


def _deployed_env(tmp_path: Path, **values: str) -> dict[str, str]:
    env = _workload_env(
        tmp_path,
        FDAI_EXECUTION_VENUE="deployed",
        FDAI_OPERATIONAL_EVIDENCE_ANCHORS_JSON=anchors_json(
            venue="deployed",
            evidence_class="live",
            overrides={
                "anchor:operational-evidence-verifier": "verifier-principal",
                "anchor:core-runtime": "core-executor",
                "anchor:isolated-executor": "isolated-executor",
                "anchor:dev-operations-gateway-executor": "dev-gateway-executor",
                "anchor:vertical-effect-executors": "vertical-effect-anchor",
                "anchor:deploy-runner": "deploy-runner",
            },
        ),
        FDAI_OPERATIONAL_EVIDENCE_CORE_EXECUTOR_PRINCIPAL_ID="core-executor",
        FDAI_OPERATIONAL_EVIDENCE_ISOLATED_EXECUTOR_PRINCIPAL_ID="isolated-executor",
        FDAI_OPERATIONAL_EVIDENCE_DEV_GATEWAY_EXECUTOR_PRINCIPAL_ID="dev-gateway-executor",
        FDAI_OPERATIONAL_EVIDENCE_VERTICAL_EXECUTOR_PRINCIPALS_JSON=(
            '["change-executor","resilience-executor","finops-executor"]'
        ),
        FDAI_OPERATIONAL_EVIDENCE_DEPLOY_RUNNER_PRINCIPAL_ID="deploy-runner",
        FDAI_OPERATIONAL_EVIDENCE_ROLE_READBACK_SCOPES_JSON=f'["{_RG}"]',
        FDAI_OPERATIONAL_EVIDENCE_ALLOWED_ROLE_SCOPES_JSON=(
            '{"AcrPull":["'
            + _REGISTRY
            + '"],"Key Vault Secrets User":["'
            + _DSN_SECRET
            + '"],"Monitoring Reader":["'
            + _RG
            + '"],"Reader":["'
            + _RG
            + '"]}'
        ),
    )
    env.update(values)
    return env


class _Caller:
    def authenticate(self, _request: object) -> str:
        return "fdai_core"


class _RoleReader:
    def __init__(self, readback: VerifierOwnRoleReadback | Exception) -> None:
        self._readback = readback

    async def read(self) -> VerifierOwnRoleReadback:
        if isinstance(self._readback, Exception):
            raise self._readback
        return self._readback


class _PausedRoleReader:
    def __init__(self, readback: VerifierOwnRoleReadback) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self._readback = readback

    async def read(self) -> VerifierOwnRoleReadback:
        self.started.set()
        await self.release.wait()
        return self._readback


def _safe_roles(*, principal: str = "verifier-principal") -> VerifierOwnRoleReadback:
    return VerifierOwnRoleReadback(
        principal_id=principal,
        assignments=(
            VerifierRoleAssignment(
                _REGISTRY,
                "acr-pull",
                "AcrPull",
                data_actions=("Microsoft.ContainerRegistry/registries/pull/read",),
            ),
            VerifierRoleAssignment(_RG, "reader", "Reader", actions=("*/read",)),
            VerifierRoleAssignment(
                _DSN_SECRET,
                "kv-secrets",
                "Key Vault Secrets User",
                actions=("Microsoft.KeyVault/vaults/secrets/getSecret/action",),
            ),
            VerifierRoleAssignment(
                _RG,
                "monitor-reader",
                "Monitoring Reader",
                actions=(
                    "Microsoft.OperationalInsights/workspaces/search/action",
                    "*/read",
                ),
            ),
        ),
        complete=True,
        observed_scopes=(_RG,),
    )


def _writer_exclusive() -> ProofStoreGrantReadback:
    return ProofStoreGrantReadback(
        writer_role="fdai_operational_evidence_verifier",
        reader_roles=("fdai_core",),
        insert_holders=("fdai_operational_evidence_verifier",),
        mutation_holders=(),
        writer_role_members=(),
        immutability_guards=("operational_evidence_admissions_immutable",),
        expected_guards=("operational_evidence_admissions_immutable",),
    )


async def _healthy_sources(_self: object) -> dict[str, OperationalEvidenceSourceHealth]:
    return {
        "operator-service.test-context-outbox": OperationalEvidenceSourceHealth.HEALTHY,
        "core-control-plane.test-context-store": OperationalEvidenceSourceHealth.HEALTHY,
    }


async def _healthy_semantic(_self: object) -> dict[str, OperationalEvidenceSourceHealth]:
    return {"core-control-plane.case-history": OperationalEvidenceSourceHealth.HEALTHY}


def test_deployed_workload_requires_authenticator_and_complete_executor_anchors(
    tmp_path: Path,
) -> None:
    with pytest.raises(RuntimeError, match="caller authenticator"):
        build_verifier_workload(_deployed_env(tmp_path), root=tmp_path)
    with pytest.raises(RuntimeError, match="executor anchors"):
        env = _deployed_env(tmp_path, FDAI_OPERATIONAL_EVIDENCE_DEPLOY_RUNNER_PRINCIPAL_ID="")
        build_verifier_workload(env, root=tmp_path, caller_authenticator=_Caller())


def test_deployed_workload_rejects_verifier_equal_to_executor_anchor(tmp_path: Path) -> None:
    env = _deployed_env(
        tmp_path,
        FDAI_OPERATIONAL_EVIDENCE_CORE_EXECUTOR_PRINCIPAL_ID="verifier-principal",
    )
    with pytest.raises(RuntimeError, match="executor anchors|executor-class"):
        build_verifier_workload(env, root=tmp_path, caller_authenticator=_Caller())


async def test_deployed_startup_stays_unready_until_own_role_readback_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def grants(*_args: object, **_kwargs: object) -> ProofStoreGrantReadback:
        return _writer_exclusive()

    monkeypatch.setattr(operational_evidence_server, "read_proof_store_grants", grants)
    monkeypatch.setattr(
        operational_evidence_server.PostgresTestContextEvidenceSources,
        "source_health",
        _healthy_sources,
    )
    workload = build_verifier_workload(
        _deployed_env(tmp_path),
        root=tmp_path,
        caller_authenticator=_Caller(),
        own_role_reader=_RoleReader(_safe_roles()),
    )
    assert workload.readiness.state == "unavailable"
    await workload.probe()
    assert workload.readiness.state == "ready"


async def test_deployed_observation_source_binds_under_verifier_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def grants(*_args: object, **_kwargs: object) -> ProofStoreGrantReadback:
        return _writer_exclusive()

    monkeypatch.setattr(operational_evidence_server, "read_proof_store_grants", grants)
    monkeypatch.setattr(
        operational_evidence_server.PostgresTestContextEvidenceSources,
        "source_health",
        _healthy_sources,
    )
    monkeypatch.setattr(
        operational_evidence_server.PostgresSemanticAuthenticationReceiptSource,
        "source_health",
        _healthy_semantic,
    )
    env = _deployed_env(
        tmp_path,
        AZURE_CLIENT_ID="verifier-client",
        FDAI_OPERATIONAL_EVIDENCE_OBSERVATION_METRIC_WORKSPACE_ID="workspace",
        FDAI_OPERATIONAL_EVIDENCE_OBSERVATION_METRIC_QUERIES_JSON=json.dumps(
            {
                "cpu_percent": {
                    "kql": "Perf | project TimeGenerated, Value, resource_id",
                    "value_column": "Value",
                    "label_columns": ["resource_id"],
                }
            }
        ),
        FDAI_OPERATIONAL_EVIDENCE_OBSERVATION_SCOPE_ROWS_JSON=json.dumps(
            [
                {
                    "target_ref": "resource-1",
                    "signal_code": "cpu_percent",
                    "policy_revision": "policy:1",
                    "access_scope_digest": "a" * 64,
                    "metric_name": "cpu_percent",
                    "dimensions": {"resource_id": "resource-1"},
                    "aggregation": "avg",
                    "service_impact": "none",
                    "protected_signal": False,
                    "operating_scope_coverage": "complete",
                    "dependency_health": "healthy",
                }
            ]
        ),
    )

    workload = build_verifier_workload(
        env,
        root=tmp_path,
        caller_authenticator=_Caller(),
        own_role_reader=_RoleReader(_safe_roles()),
    )
    await workload.probe()

    assert "operational-test-observation" in workload.engine.bound_purposes()
    assert workload.readiness.source_health["azure-monitor.metrics"].value == "healthy"
    assert workload.readiness.source_health["operating-scope.dependency-health"].value == "healthy"


async def test_deployed_probe_does_not_publish_ready_while_role_read_is_in_flight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def grants(*_args: object, **_kwargs: object) -> ProofStoreGrantReadback:
        return _writer_exclusive()

    monkeypatch.setattr(operational_evidence_server, "read_proof_store_grants", grants)
    monkeypatch.setattr(
        operational_evidence_server.PostgresTestContextEvidenceSources,
        "source_health",
        _healthy_sources,
    )
    role_reader = _PausedRoleReader(_safe_roles())
    workload = build_verifier_workload(
        _deployed_env(tmp_path),
        root=tmp_path,
        caller_authenticator=_Caller(),
        own_role_reader=role_reader,
    )
    probe = asyncio.create_task(workload.probe())
    await role_reader.started.wait()
    blocked = workload.engine._blocked
    assert workload.readiness.state == "unavailable"
    assert await blocked() is True
    role_reader.release.set()
    await probe
    assert workload.readiness.state == "ready"


@pytest.mark.parametrize(
    ("reader", "reason"),
    [
        (
            _RoleReader(
                VerifierOwnRoleReadback(
                    principal_id="verifier-principal",
                    assignments=(VerifierRoleAssignment("scope", "unknown", ""),),
                    complete=True,
                    observed_scopes=("scope",),
                )
            ),
            "role_definition_unresolved",
        ),
        (_RoleReader(OSError("arm unavailable")), "role_readback_unavailable"),
        (_RoleReader(httpx.ReadTimeout("arm timeout")), "role_readback_unavailable"),
        (_RoleReader(jwt.DecodeError("bad token")), "role_readback_unavailable"),
        (_RoleReader(_safe_roles(principal="other-principal")), "role_readback_principal_mismatch"),
    ],
)
async def test_deployed_startup_refuses_bad_own_role_readback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reader: _RoleReader,
    reason: str,
) -> None:
    async def grants(*_args: object, **_kwargs: object) -> ProofStoreGrantReadback:
        return _writer_exclusive()

    monkeypatch.setattr(operational_evidence_server, "read_proof_store_grants", grants)
    monkeypatch.setattr(
        operational_evidence_server.PostgresTestContextEvidenceSources,
        "source_health",
        _healthy_sources,
    )
    workload = build_verifier_workload(
        _deployed_env(tmp_path),
        root=tmp_path,
        caller_authenticator=_Caller(),
        own_role_reader=reader,
    )
    await workload.probe()
    assert workload.readiness.state == "unavailable"
    assert reason in workload.readiness.reasons


def test_deployed_venue_refuses_env_provided_role_lists(tmp_path: Path) -> None:
    env = _deployed_env(
        tmp_path,
        FDAI_OPERATIONAL_EVIDENCE_OWN_ROLE_ASSIGNMENTS_JSON="[]",
    )
    with pytest.raises(RuntimeError, match="cannot come from environment"):
        build_verifier_workload(env, root=tmp_path, caller_authenticator=_Caller())

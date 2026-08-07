"""Read-only deployment preflight composition for ``fdaictl``."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Final, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from fdai.core.deploy_preflight import DeploymentReadinessReport, PreflightAnalyzer
from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
from fdai.delivery.azure.onboarding import AzureOnboardingProbeConfig, AzureResourceProbe
from fdai.delivery.azure.preflight import (
    ArmClientConfig,
    AzureArmClient,
    AzureIdentityRbacProbe,
    AzurePolicyGuardrailProbe,
    AzurePolicyProbeConfig,
    AzureQuotaProbe,
    AzureQuotaProbeConfig,
    AzureSecretConfigProbe,
    AzureSecretProbeConfig,
    QuotaCheck,
)
from fdai.deployment_cli.onboarding import OnboardingError, load_environment
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.feasibility_probe import (
    FeasibilityProbe,
    PreflightTarget,
    ProbeCategory,
)
from fdai.shared.providers.local import DenylistResourceTypeProbe, EgressDenylistProbe
from fdai.shared.providers.workload_identity import WorkloadIdentity

PREFLIGHT_INPUT_SCHEMA: Final = "fdai.deployment.preflight-input.v1"
PREFLIGHT_OUTPUT_SCHEMA: Final = "fdai.deployment-cli.preflight.v1"
_NON_CLOUD_TERRAFORM_RESOURCE_TYPES: Final = frozenset({"terraform_data"})


class _PreflightModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class StaticPolicyInput(_PreflightModel):
    """Grounded local policy facts supplied by an approved discovery step."""

    denied_resource_types: tuple[str, ...] = ()
    blocked_egress_hosts: tuple[str, ...] = ()
    policy_source: Annotated[str, Field(min_length=1)]
    firewall_source: Annotated[str, Field(min_length=1)]


class LiveQuotaCheckInput(_PreflightModel):
    quota_name: Annotated[str, Field(min_length=1, max_length=128)]
    required: Annotated[int, Field(ge=1)] = 1


class LiveIdentityRbacInput(_PreflightModel):
    executor_principal_id: Annotated[str, Field(pattern=r"^[^']{1,256}$")]
    event_role_definition_id: Annotated[str, Field(pattern=r"^[^']{1,256}$")]
    secret_role_definition_id: Annotated[str, Field(pattern=r"^[^']{1,256}$")]


SecretName = Annotated[str, Field(pattern=r"^[A-Za-z0-9-]{1,127}$")]


class LiveKeyVaultInput(_PreflightModel):
    vault_endpoint: Annotated[
        str,
        Field(pattern=r"^https://[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.vault\.azure\.net/?$"),
    ]
    required_secret_names: Annotated[
        tuple[SecretName, ...],
        Field(min_length=1, max_length=64),
    ]


class AzureLivePreflightInput(_PreflightModel):
    """Non-secret Azure read-probe configuration."""

    required_categories: tuple[ProbeCategory, ...] = ()
    resource_group: Annotated[str, Field(pattern=r"^[^']{1,90}$")] | None = None
    arm_resource_type_map: dict[str, str] = Field(default_factory=dict)
    quota_checks: Annotated[tuple[LiveQuotaCheckInput, ...], Field(max_length=64)] = ()
    identity_rbac: LiveIdentityRbacInput | None = None
    key_vault: LiveKeyVaultInput | None = None


class StaticPreflightInput(_PreflightModel):
    """Versioned deterministic input for a network-free preflight pass."""

    schema_version: Literal["fdai.deployment.preflight-input.v1"] = PREFLIGHT_INPUT_SCHEMA
    scope: Annotated[str, Field(min_length=1)]
    mode: Mode = Mode.SHADOW
    generated_at: Annotated[str, Field(min_length=1)]
    resource_types: tuple[str, ...] = ()
    egress_hosts: tuple[str, ...] = ()
    required_links: tuple[str, ...] = ()
    terraform_resource_type_map: dict[str, str] = Field(default_factory=dict)
    azure_live: AzureLivePreflightInput | None = None
    policy: StaticPolicyInput


class _TerraformPlanModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, str_strip_whitespace=True)


class TerraformChange(_TerraformPlanModel):
    actions: Annotated[tuple[str, ...], Field(max_length=4)] = ()


class TerraformResourceChange(_TerraformPlanModel):
    mode: str = "managed"
    type: Annotated[str, Field(min_length=1)]
    change: TerraformChange


class TerraformPlanInput(_TerraformPlanModel):
    """Bounded subset of the machine-readable ``terraform show -json`` output."""

    format_version: Annotated[str, Field(min_length=1)]
    resource_changes: Annotated[tuple[TerraformResourceChange, ...], Field(max_length=10_000)] = ()


class PreflightInputError(RuntimeError):
    """The requested preflight could not produce a complete report."""

    def to_json(self) -> str:
        return json.dumps(
            {"error": str(self), "schema_version": PREFLIGHT_OUTPUT_SCHEMA},
            sort_keys=True,
            separators=(",", ":"),
        )


class StaticPreflightResult:
    """Stable report envelope with documented CLI exit semantics."""

    def __init__(self, report: DeploymentReadinessReport) -> None:
        self.report = report

    @property
    def exit_code(self) -> int:
        if self.report.blocks_deploy:
            return 3
        if self.report.findings:
            return 2
        return 0

    def to_json(self) -> str:
        payload = {
            "report": self.report.to_dict(),
            "schema_version": PREFLIGHT_OUTPUT_SCHEMA,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


async def run_static_preflight(path: Path) -> StaticPreflightResult:
    """Validate one static input and run the existing deterministic analyzer."""
    request = _load_preflight_input(path)
    return await _run_preflight_request(request)


def _load_preflight_input(path: Path) -> StaticPreflightInput:
    try:
        return StaticPreflightInput.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise PreflightInputError(f"preflight input at {path} is invalid or unreadable") from exc


async def _run_preflight_request(
    request: StaticPreflightInput,
    *,
    extra_probes: Sequence[FeasibilityProbe] = (),
) -> StaticPreflightResult:
    analyzer = PreflightAnalyzer(
        (
            DenylistResourceTypeProbe(
                denied_types=frozenset(request.policy.denied_resource_types),
                policy_source=request.policy.policy_source,
            ),
            EgressDenylistProbe(
                blocked_hosts=frozenset(request.policy.blocked_egress_hosts),
                firewall_source=request.policy.firewall_source,
            ),
            *extra_probes,
        ),
        mode=request.mode,
        clock=lambda: request.generated_at,
    )
    report = await analyzer.analyze(
        PreflightTarget(
            scope=request.scope,
            resource_types=request.resource_types,
            egress_hosts=request.egress_hosts,
            required_links=request.required_links,
        )
    )
    return StaticPreflightResult(report)


def load_terraform_plan_resource_types(
    path: Path,
    *,
    resource_type_map: dict[str, str],
) -> tuple[str, ...]:
    """Return CSP-neutral types created or replaced by a Terraform JSON plan."""
    try:
        plan = TerraformPlanInput.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise PreflightInputError(f"Terraform plan at {path} is invalid or unreadable") from exc

    planned_types: set[str] = set()
    missing_types: set[str] = set()
    for resource_change in plan.resource_changes:
        if resource_change.mode != "managed":
            continue
        if "create" not in resource_change.change.actions:
            continue
        if resource_change.type in _NON_CLOUD_TERRAFORM_RESOURCE_TYPES:
            continue
        neutral_type = resource_type_map.get(resource_change.type)
        if neutral_type is None:
            missing_types.add(resource_change.type)
            continue
        planned_types.add(neutral_type)
    if missing_types:
        missing = ", ".join(sorted(missing_types))
        raise PreflightInputError(f"Terraform resource type mapping is missing for: {missing}")
    return tuple(sorted(planned_types))


async def run_terraform_plan_preflight(
    input_path: Path,
    terraform_plan_path: Path,
) -> StaticPreflightResult:
    """Merge one Terraform JSON plan into the validated deterministic target."""
    request = _load_preflight_input(input_path)
    merged = _merge_terraform_plan(request, terraform_plan_path)
    return await _run_preflight_request(merged)


def _merge_terraform_plan(
    request: StaticPreflightInput,
    terraform_plan_path: Path,
) -> StaticPreflightInput:
    plan_types = load_terraform_plan_resource_types(
        terraform_plan_path,
        resource_type_map=request.terraform_resource_type_map,
    )
    merged_types = tuple(sorted(set(request.resource_types) | set(plan_types)))
    return request.model_copy(update={"resource_types": merged_types})


async def run_azure_live_preflight(
    input_path: Path,
    environment_path: Path,
    terraform_plan_path: Path | None = None,
    *,
    identity: WorkloadIdentity | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> StaticPreflightResult:
    """Run static plus bounded read-only Azure Policy and quota probes."""
    request = _load_preflight_input(input_path)
    if terraform_plan_path is not None:
        request = _merge_terraform_plan(request, terraform_plan_path)
    live = request.azure_live
    if live is None:
        raise PreflightInputError("preflight input is missing azure_live configuration")
    try:
        environment = load_environment(environment_path)
    except OnboardingError as exc:
        raise PreflightInputError(
            "Azure environment configuration is invalid or unreadable"
        ) from exc

    resolved_identity = identity or AsyncAzureCliWorkloadIdentity()
    if http_client is not None:
        return await _run_azure_live_request(
            request,
            live,
            subscription_id=str(environment.azure.subscription_id),
            location=environment.azure.region,
            identity=resolved_identity,
            http_client=http_client,
        )
    async with httpx.AsyncClient() as owned_client:
        return await _run_azure_live_request(
            request,
            live,
            subscription_id=str(environment.azure.subscription_id),
            location=environment.azure.region,
            identity=resolved_identity,
            http_client=owned_client,
        )


async def _run_azure_live_request(
    request: StaticPreflightInput,
    live: AzureLivePreflightInput,
    *,
    subscription_id: str,
    location: str,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
) -> StaticPreflightResult:
    _validate_required_live_categories(live)
    arm_client = AzureArmClient(
        identity=identity,
        http_client=http_client,
        config=ArmClientConfig(timeout_seconds=20.0, max_pages=8),
    )
    probes: list[FeasibilityProbe] = [
        AzurePolicyGuardrailProbe(
            client=arm_client,
            config=AzurePolicyProbeConfig(
                subscription_id=subscription_id,
                resource_group=live.resource_group,
                resource_type_map=live.arm_resource_type_map,
            ),
        )
    ]
    if live.quota_checks:
        probes.append(
            AzureQuotaProbe(
                client=arm_client,
                config=AzureQuotaProbeConfig(
                    subscription_id=subscription_id,
                    location=location,
                    checks=tuple(
                        QuotaCheck(check.quota_name, required=check.required)
                        for check in live.quota_checks
                    ),
                ),
            )
        )
    if live.identity_rbac is not None:
        if live.resource_group is None:
            raise PreflightInputError(
                "azure_live.resource_group is required for identity_rbac checks"
            )
        identity_config = live.identity_rbac
        resource_reader = AzureResourceProbe(
            config=AzureOnboardingProbeConfig(
                subscription_id=subscription_id,
                resource_group=live.resource_group,
                executor_principal_id=identity_config.executor_principal_id,
                event_role_definition_id=identity_config.event_role_definition_id,
                secret_role_definition_id=identity_config.secret_role_definition_id,
                timeout_seconds=20.0,
            ),
            identity=identity,
            http_client=http_client,
        )
        probes.append(AzureIdentityRbacProbe(reader=resource_reader))
    if live.key_vault is not None:
        probes.append(
            AzureSecretConfigProbe(
                config=AzureSecretProbeConfig(
                    vault_endpoint=live.key_vault.vault_endpoint,
                    required_secret_names=live.key_vault.required_secret_names,
                ),
                identity=identity,
                http_client=http_client,
            )
        )
    try:
        return await _run_preflight_request(request, extra_probes=probes)
    except ExceptionGroup as exc:
        raise PreflightInputError(
            "live Azure preflight probe failed; no clear result was produced"
        ) from exc


def _validate_required_live_categories(live: AzureLivePreflightInput) -> None:
    configured = {ProbeCategory.POLICY_GUARDRAIL}
    if live.quota_checks:
        configured.add(ProbeCategory.QUOTA_CAPACITY)
    if live.identity_rbac is not None:
        configured.add(ProbeCategory.IDENTITY_RBAC)
    if live.key_vault is not None:
        configured.add(ProbeCategory.SECRET_CONFIG)
    missing = set(live.required_categories) - configured
    if missing:
        names = ", ".join(sorted(category.value for category in missing))
        raise PreflightInputError(f"required live preflight categories are not configured: {names}")


__all__ = [
    "PREFLIGHT_INPUT_SCHEMA",
    "PREFLIGHT_OUTPUT_SCHEMA",
    "AzureLivePreflightInput",
    "LiveIdentityRbacInput",
    "LiveKeyVaultInput",
    "PreflightInputError",
    "StaticPreflightInput",
    "StaticPreflightResult",
    "load_terraform_plan_resource_types",
    "run_azure_live_preflight",
    "run_static_preflight",
    "run_terraform_plan_preflight",
]

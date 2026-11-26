"""Private full-topology inputs for the Hub workload Terraform state handoff."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.private_output import write_private_bytes

INVENTORY_SCHEMA = "fdai.hub-workload-state-inventory.v1"
_ADDRESS = re.compile(
    r"kubernetes_(?:deployment_v1|service_v1|cron_job_v1|horizontal_pod_autoscaler_v2)"
    r"\.[a-z][a-z0-9_]*(?:\[[\"'][a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?[\"']\])?\Z",
    re.ASCII,
)
_IMPORT_ID = re.compile(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?/[A-Za-z0-9._/-]{1,253}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z", re.ASCII)
_KIND_RESOURCES = {
    "Deployment": ("kubernetes_deployment_v1", "workload", "deployments"),
    "Service": ("kubernetes_service_v1", "workload", "services"),
    "CronJob": ("kubernetes_cron_job_v1", "job", "cron_jobs"),
    "HorizontalPodAutoscaler": (
        "kubernetes_horizontal_pod_autoscaler_v2",
        "workload",
        "horizontal_pod_autoscalers",
    ),
}


@dataclass(frozen=True, slots=True)
class WorkloadStateObject:
    address: str
    import_id: str
    render_digest: str

    def __post_init__(self) -> None:
        if (
            _ADDRESS.fullmatch(self.address) is None
            or _IMPORT_ID.fullmatch(self.import_id) is None
            or _DIGEST.fullmatch(self.render_digest) is None
        ):
            raise ValueError("Hub workload state object is invalid")


def build_handoff_inventory(
    native_scope: Mapping[str, object],
    rendered_manifests: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Bind one exact native scope to Terraform addresses, import IDs, and render digests."""

    namespace = native_scope.get("namespace")
    if not isinstance(namespace, str):
        raise ValueError(  # noqa: TRY004 - normalize untrusted JSON into one operator error
            "Hub workload native scope namespace is invalid"
        )
    expected = _native_resources(native_scope)
    objects: list[WorkloadStateObject] = []
    actual: set[tuple[str, str]] = set()
    tfvars: dict[str, dict[str, str]] = {
        "deployments": {},
        "services": {},
        "cron_jobs": {},
        "horizontal_pod_autoscalers": {},
    }
    for manifest in rendered_manifests:
        kind = manifest.get("kind")
        metadata = manifest.get("metadata")
        if (
            not isinstance(kind, str)
            or kind not in _KIND_RESOURCES
            or not isinstance(metadata, Mapping)
            or not isinstance(name := metadata.get("name"), str)
            or metadata.get("namespace") != namespace
        ):
            raise ValueError("Hub workload rendered manifest is invalid")
        key = (kind, name)
        if key in actual:
            raise ValueError("Hub workload rendered manifests must be unique")
        actual.add(key)
        resource_type, resource_name, variable_name = _KIND_RESOURCES[kind]
        address = f'{resource_type}.{resource_name}["{name}"]'
        import_id = f"{namespace}/{name}"
        objects.append(
            WorkloadStateObject(
                address=address,
                import_id=import_id,
                render_digest="sha256:" + canonical_digest(manifest),
            )
        )
        tfvars[variable_name][name] = import_id
    if actual != expected:
        raise ValueError("Hub workload rendered inventory differs from the native scope")
    ordered = sorted(objects, key=lambda item: item.address)
    body: dict[str, object] = {
        "schema_version": INVENTORY_SCHEMA,
        "namespace": namespace,
        "objects": [
            {
                "address": item.address,
                "import_id": item.import_id,
                "render_digest": item.render_digest,
            }
            for item in ordered
        ],
        "terraform_variables": {
            "namespace": namespace,
            **{key: dict(sorted(value.items())) for key, value in tfvars.items()},
        },
    }
    return body | {"inventory_digest": "sha256:" + canonical_digest(body)}


def write_handoff_operator_inputs(
    destination: Path,
    native_scope: Mapping[str, object],
    rendered_manifests: Sequence[Mapping[str, object]],
) -> tuple[Path, Path, Path]:
    """Write exact Terraform variables, verified inventory, and phase commands."""

    inventory = build_handoff_inventory(native_scope, rendered_manifests)
    inventory_path = destination / "workload-handoff-inventory.json"
    tfvars_path = destination / "workload-handoff.tfvars.json"
    commands_path = destination / "workload-handoff-commands.txt"
    write_private_bytes(inventory_path, canonical_bytes(inventory) + b"\n")
    write_private_bytes(
        tfvars_path,
        canonical_bytes(inventory["terraform_variables"]) + b"\n",
    )
    write_private_bytes(commands_path, _commands().encode())
    return inventory_path, tfvars_path, commands_path


def read_handoff_inventory(document: Mapping[str, object]) -> tuple[WorkloadStateObject, ...]:
    """Verify and load a generated handoff inventory without trusting its Terraform variables."""

    digest = document.get("inventory_digest")
    body = {key: value for key, value in document.items() if key != "inventory_digest"}
    objects = body.get("objects")
    if (
        body.get("schema_version") != INVENTORY_SCHEMA
        or not isinstance(body.get("namespace"), str)
        or not isinstance(objects, list)
        or not objects
        or not isinstance(digest, str)
        or digest != "sha256:" + canonical_digest(body)
    ):
        raise ValueError("Hub workload state inventory is invalid")
    result: list[WorkloadStateObject] = []
    for item in objects:
        if not isinstance(item, Mapping):
            raise ValueError(  # noqa: TRY004 - normalize untrusted JSON into one operator error
                "Hub workload state inventory is invalid"
            )
        result.append(
            WorkloadStateObject(
                address=str(item.get("address", "")),
                import_id=str(item.get("import_id", "")),
                render_digest=str(item.get("render_digest", "")),
            )
        )
    if len({item.address for item in result}) != len(result):
        raise ValueError("Hub workload state inventory is invalid")
    return tuple(result)


def _native_resources(scope: Mapping[str, object]) -> set[tuple[str, str]]:
    components = _names(scope.get("components"), required=True)
    services = _names(scope.get("service_components"), required=False)
    schedules = _names(scope.get("scheduled_components"), required=False)
    autoscalers = _names(scope.get("autoscaled_components"), required=False)
    if not services and scope.get("service_components") is None:
        services = components
    if not services <= components or not autoscalers <= components or components & schedules:
        raise ValueError("Hub workload native scope is invalid")
    return (
        {("Deployment", name) for name in components}
        | {("Service", name) for name in services}
        | {("CronJob", name) for name in schedules}
        | {("HorizontalPodAutoscaler", name) for name in autoscalers}
    )


def _names(value: object, *, required: bool) -> set[str]:
    if value is None and not required:
        return set()
    if (
        not isinstance(value, (list, tuple))
        or (required and not value)
        or any(not isinstance(item, str) for item in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError("Hub workload native scope is invalid")
    return set(value)


def _commands() -> str:
    return """\
# Replace angle-bracket values with private operator paths. Reuse one absolute backend path.
umask 077
terraform -chdir=infra/hub-workload-state-handoff/import init -reconfigure -backend-config=path=<absolute-private-state-path>
terraform -chdir=infra/hub-workload-state-handoff/import plan -var-file=<workload-handoff.tfvars.json> -var=kubeconfig_path=<private-kubeconfig> -var=kubeconfig_context=<kube-context> -out=<import-plan>
terraform show -json <import-plan> > <import-plan.json>
fdai-lifecycle-manager verify-workload-handoff-plan --phase import --inventory <workload-handoff-inventory.json> --plan-json <import-plan.json> --destination <import-verification.json>
terraform -chdir=infra/hub-workload-state-handoff/import apply <import-plan>
terraform -chdir=infra/hub-workload-state-handoff/import plan -detailed-exitcode -var-file=<workload-handoff.tfvars.json> -var=kubeconfig_path=<private-kubeconfig> -var=kubeconfig_context=<kube-context> -out=<import-zero-plan>
terraform show -json <import-zero-plan> > <import-zero-plan.json>
fdai-lifecycle-manager verify-workload-handoff-plan --phase zero-change --inventory <workload-handoff-inventory.json> --plan-json <import-zero-plan.json> --destination <import-zero-verification.json>

terraform -chdir=infra/hub-workload-state-handoff/release init -reconfigure -backend-config=path=<absolute-private-state-path>
terraform -chdir=infra/hub-workload-state-handoff/release plan -var-file=<workload-handoff.tfvars.json> -var=kubeconfig_path=<private-kubeconfig> -var=kubeconfig_context=<kube-context> -out=<release-plan>
terraform show -json <release-plan> > <release-plan.json>
fdai-lifecycle-manager verify-workload-handoff-plan --phase release --inventory <workload-handoff-inventory.json> --plan-json <release-plan.json> --destination <release-verification.json>
terraform -chdir=infra/hub-workload-state-handoff/release apply <release-plan>

# Rollback only after the Agent reconciliation-release receipt is retained.
terraform -chdir=infra/hub-workload-state-handoff/import init -reconfigure -backend-config=path=<absolute-private-state-path>
terraform -chdir=infra/hub-workload-state-handoff/import plan -var-file=<workload-handoff.tfvars.json> -var=kubeconfig_path=<private-kubeconfig> -var=kubeconfig_context=<kube-context> -out=<rollback-import-plan>
terraform show -json <rollback-import-plan> > <rollback-import-plan.json>
fdai-lifecycle-manager verify-workload-handoff-plan --phase import --inventory <workload-handoff-inventory.json> --plan-json <rollback-import-plan.json> --destination <rollback-import-verification.json>
terraform -chdir=infra/hub-workload-state-handoff/import apply <rollback-import-plan>
terraform -chdir=infra/hub-workload-state-handoff/import plan -detailed-exitcode -var-file=<workload-handoff.tfvars.json> -var=kubeconfig_path=<private-kubeconfig> -var=kubeconfig_context=<kube-context> -out=<rollback-zero-plan>
terraform show -json <rollback-zero-plan> > <rollback-zero-plan.json>
fdai-lifecycle-manager verify-workload-handoff-plan --phase zero-change --inventory <workload-handoff-inventory.json> --plan-json <rollback-zero-plan.json> --destination <rollback-zero-verification.json>
"""

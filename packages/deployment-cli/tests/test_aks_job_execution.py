from __future__ import annotations

import copy
from collections.abc import Callable

import pytest

from fdai_deployment_cli.aks_job_execution import (
    job_terminal_state,
    materialize_cronjob_execution,
    protected_cronjob_template_digest,
    validate_existing_job,
)

_REVISION = "a" * 40
_TARGET = "b" * 64
_IMAGE = "example.azurecr.io/fdai@sha256:" + "c" * 64
_SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"
_IDENTITY_BINDING_DIGEST = "d" * 64


def _scheduled_job(*, name: str = "inventory") -> dict[str, object]:
    catalog_review = name == "catalog-review"
    environment = (
        {
            "FDAI_CATALOG_REVIEW_FROZEN_MANIFEST": (
                "services/core-control-plane/tests/scenarios/operational-learning/"
                "v2026.08-governed-learning.json"
            ),
            "FDAI_CATALOG_REVIEW_SCENARIO_DIR": (
                "services/core-control-plane/tests/scenarios/v2026.09"
            ),
            "FDAI_GITOPS_DEFAULT_BRANCH": "main",
        }
        if catalog_review
        else {
            "FDAI_INVENTORY_SCOPES": _SUBSCRIPTION,
            "FDAI_INVENTORY_SOURCES": "arg,arm",
        }
    )
    return {
        "component": name,
        "image": _IMAGE,
        "identity_resource_id": "opaque",
        "identity_client_id": "opaque",
        "command": [
            "python",
            "-m",
            (
                "fdai.runtime.operational_catalog_review_trigger"
                if catalog_review
                else "fdai.delivery.inventory_sync_cli"
            ),
        ],
        "args": [],
        "schedule": "0 0 1 1 *" if catalog_review else "* * * * *",
        "suspend": catalog_review,
        "deadline_seconds": 300 if catalog_review else 900,
        "retry_limit": 0 if catalog_review else 1,
        "cpu": "500m",
        "memory": "1Gi",
        "environment": environment,
        "secret_environment": (
            {"FDAI_GITHUB_APP_PRIVATE_KEY": "catalog-review-private-key"}
            if catalog_review
            else {"FDAI_INVENTORY_DSN": "inventory-job"}
        ),
    }


def _cronjob(*, name: str = "inventory") -> dict[str, object]:
    job = _scheduled_job(name=name)
    labels = {
        "app.kubernetes.io/name": name,
        "app.kubernetes.io/component": str(job["component"]),
        "app.kubernetes.io/managed-by": "terraform",
        "fdai.io/runtime": "aks",
        "fdai.io/source-commit": _REVISION,
    }
    secret_environment = job["secret_environment"]
    assert isinstance(secret_environment, dict)
    environment = job["environment"]
    assert isinstance(environment, dict)
    environment_entries = [
        {"name": key, "value": value} for key, value in sorted(environment.items())
    ]
    environment_entries.extend(
        {
            "name": key,
            "valueFrom": {
                "secretKeyRef": {
                    "name": f"{name}-job",
                    "key": key,
                }
            },
        }
        for key in sorted(secret_environment)
    )
    has_secrets = bool(secret_environment)
    return {
        "apiVersion": "batch/v1",
        "kind": "CronJob",
        "metadata": {
            "name": name,
            "namespace": "fdai-runtime",
            "labels": labels,
        },
        "spec": {
            "schedule": job["schedule"],
            "suspend": job["suspend"],
            "concurrencyPolicy": "Forbid",
            "successfulJobsHistoryLimit": 3,
            "failedJobsHistoryLimit": 3,
            "jobTemplate": {
                "metadata": {"labels": labels},
                "spec": {
                    "completions": 1,
                    "parallelism": 1,
                    "backoffLimit": job["retry_limit"],
                    "activeDeadlineSeconds": job["deadline_seconds"],
                    "ttlSecondsAfterFinished": 3600,
                    "template": {
                        "metadata": {
                            "labels": {
                                **labels,
                                "azure.workload.identity/use": "true",
                            }
                        },
                        "spec": {
                            "serviceAccountName": f"{name}-job",
                            "automountServiceAccountToken": True,
                            "restartPolicy": "Never",
                            "nodeSelector": {"fdai.io/pool": "runtime"},
                            "securityContext": {
                                "runAsNonRoot": True,
                                "seccompProfile": {"type": "RuntimeDefault"},
                            },
                            "containers": [
                                {
                                    "name": name,
                                    "image": job["image"],
                                    "imagePullPolicy": "IfNotPresent",
                                    "command": job["command"],
                                    "args": job["args"],
                                    "env": environment_entries,
                                    "resources": {
                                        "requests": {
                                            "cpu": job["cpu"],
                                            "memory": job["memory"],
                                        },
                                        "limits": {
                                            "cpu": job["cpu"],
                                            "memory": job["memory"],
                                        },
                                    },
                                    "securityContext": {
                                        "allowPrivilegeEscalation": False,
                                        "runAsNonRoot": True,
                                        "capabilities": {"drop": ["ALL"]},
                                    },
                                    **(
                                        {
                                            "volumeMounts": [
                                                {
                                                    "name": "secrets",
                                                    "mountPath": "/mnt/secrets-store",
                                                    "readOnly": True,
                                                }
                                            ]
                                        }
                                        if has_secrets
                                        else {}
                                    ),
                                }
                            ],
                            **(
                                {
                                    "volumes": [
                                        {
                                            "name": "secrets",
                                            "csi": {
                                                "driver": "secrets-store.csi.k8s.io",
                                                "readOnly": True,
                                                "volumeAttributes": {
                                                    "secretProviderClass": f"{name}-job"
                                                },
                                            },
                                        }
                                    ]
                                }
                                if has_secrets
                                else {}
                            ),
                        },
                    },
                },
            },
        },
    }


def _template_digest(*, name: str = "inventory") -> str:
    return protected_cronjob_template_digest(
        _scheduled_job(name=name),
        template_name=name,
        namespace="fdai-runtime",
        source_revision=_REVISION,
    )


def _materialize() -> object:
    return materialize_cronjob_execution(
        _cronjob(),
        purpose="inventory",
        source_revision=_REVISION,
        target_binding=_TARGET,
        expected_template_name="inventory",
        expected_container_name="inventory",
        expected_image=_IMAGE,
        expected_command=("python", "-m", "fdai.delivery.inventory_sync_cli"),
        expected_service_account="inventory-job",
        args=("--initial",),
        environment={
            "FDAI_INVENTORY_PROGRESS_ATTEMPT_ID": "attempt.example",
            "FDAI_INVENTORY_PROGRESS_RUN_ID": f"genesis.{_REVISION}",
            "FDAI_INVENTORY_RESOURCE_TYPES": "",
            "FDAI_INVENTORY_SCOPES": _SUBSCRIPTION,
            "FDAI_INVENTORY_SOURCES": "arg,arm",
        },
        require_suspended=False,
        protected_template_digest=_template_digest(),
        protected_identity_binding_digest=_IDENTITY_BINDING_DIGEST,
    )


def _container(cronjob: dict[str, object]) -> dict[str, object]:
    return cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]  # type: ignore[index,return-value]


def _environment(cronjob: dict[str, object], name: str) -> dict[str, object]:
    return next(
        item
        for item in _container(cronjob)["env"]
        if item["name"] == name  # type: ignore[index]
    )


def test_materializes_exact_read_only_inventory_job() -> None:
    execution = _materialize()
    assert execution.name.startswith("fdai-inventory-")
    assert len(execution.execution_digest) == 64
    metadata = execution.manifest["metadata"]
    assert metadata["annotations"]["fdai.io/target-binding"] == _TARGET
    assert metadata["annotations"]["fdai.io/template-digest"] == _template_digest()
    pod = execution.manifest["spec"]["template"]["spec"]
    assert pod["serviceAccountName"] == "inventory-job"
    container = pod["containers"][0]
    assert container["image"] == _IMAGE
    assert container["args"] == ["--initial"]
    environment = {item["name"]: item for item in container["env"]}
    assert environment["FDAI_INVENTORY_DSN"]["valueFrom"]["secretKeyRef"] == {
        "name": "inventory-job",
        "key": "FDAI_INVENTORY_DSN",
    }
    assert environment["FDAI_INVENTORY_SCOPES"]["value"] == _SUBSCRIPTION
    assert environment["FDAI_INVENTORY_SOURCES"]["value"] == "arg,arm"
    assert environment["FDAI_INVENTORY_RESOURCE_TYPES"]["value"] == ""


def test_protected_template_may_explicitly_review_env_from() -> None:
    scheduled_job = _scheduled_job()
    scheduled_job["env_from"] = [{"configMapRef": {"name": "reviewed-runtime-values"}}]
    cronjob = _cronjob()
    _container(cronjob)["envFrom"] = [{"configMapRef": {"name": "reviewed-runtime-values"}}]
    digest = protected_cronjob_template_digest(
        scheduled_job,
        template_name="inventory",
        namespace="fdai-runtime",
        source_revision=_REVISION,
    )

    execution = materialize_cronjob_execution(
        cronjob,
        purpose="inventory",
        source_revision=_REVISION,
        target_binding=_TARGET,
        expected_template_name="inventory",
        expected_container_name="inventory",
        expected_image=_IMAGE,
        expected_command=("python", "-m", "fdai.delivery.inventory_sync_cli"),
        expected_service_account="inventory-job",
        args=("--initial",),
        protected_template_digest=digest,
        protected_identity_binding_digest=_IDENTITY_BINDING_DIGEST,
    )

    assert execution.manifest["spec"]["template"]["spec"]["containers"][0]["envFrom"] == [  # type: ignore[index]
        {"configMapRef": {"name": "reviewed-runtime-values"}}
    ]


def test_materialization_is_content_addressed_and_replay_safe() -> None:
    first = _materialize()
    second = _materialize()
    assert first == second
    existing = copy.deepcopy(first.manifest)
    existing["status"] = {
        "failed": 2,
        "succeeded": 1,
        "conditions": [{"type": "Complete", "status": "True"}],
    }

    validate_existing_job(existing, expected=first)

    assert job_terminal_state(existing) == "succeeded"


def test_rejects_live_catalog_template_drift_in_every_protected_surface() -> None:
    cronjob = _cronjob(name="catalog-review")
    digest = _template_digest(name="catalog-review")
    mutations: tuple[Callable[[dict[str, object]], None], ...] = (
        lambda value: _environment(value, "FDAI_CATALOG_REVIEW_FROZEN_MANIFEST").__setitem__(
            "value", "other.json"
        ),
        lambda value: _environment(value, "FDAI_GITOPS_DEFAULT_BRANCH").__setitem__(
            "value", "unreviewed"
        ),
        lambda value: _environment(value, "FDAI_GITHUB_APP_PRIVATE_KEY")["valueFrom"][
            "secretKeyRef"
        ].__setitem__("name", "other-secret"),  # type: ignore[index]
        lambda value: _container(value).__setitem__("command", ["python", "-c", "pass"]),
        lambda value: _container(value).__setitem__("args", ["--unsafe"]),
        lambda value: _container(value).__setitem__(
            "envFrom", [{"secretRef": {"name": "unreviewed"}}]
        ),
        lambda value: _container(value).__setitem__("terminationMessagePath", "/tmp/unreviewed"),
        lambda value: _container(value).__setitem__(
            "volumeDevices", [{"name": "device", "devicePath": "/dev/example"}]
        ),
        lambda value: _container(value).__setitem__(
            "image", "example.azurecr.io/other@sha256:" + "d" * 64
        ),
        lambda value: value["spec"]["jobTemplate"]["spec"]["template"]["spec"].__setitem__(  # type: ignore[index]
            "serviceAccountName", "other-job"
        ),
        lambda value: value["spec"]["jobTemplate"]["spec"].__setitem__(  # type: ignore[index]
            "activeDeadlineSeconds", 301
        ),
        lambda value: (
            value["metadata"]
            .setdefault("annotations", {})
            .__setitem__(  # type: ignore[union-attr]
                "sidecar.istio.io/inject", "true"
            )
        ),
    )
    for mutate in mutations:
        changed = copy.deepcopy(cronjob)
        mutate(changed)
        with pytest.raises(ValueError, match="protected template digest"):
            materialize_cronjob_execution(
                changed,
                purpose="catalog-review",
                source_revision=_REVISION,
                target_binding=_TARGET,
                expected_template_name="catalog-review",
                expected_container_name="catalog-review",
                expected_image=_IMAGE,
                expected_command=(
                    "python",
                    "-m",
                    "fdai.runtime.operational_catalog_review_trigger",
                ),
                expected_service_account="catalog-review-job",
                args=(),
                require_suspended=True,
                protected_template_digest=digest,
                protected_identity_binding_digest=_IDENTITY_BINDING_DIGEST,
            )


def test_rejects_recovered_job_drift_outside_previously_selected_fields() -> None:
    expected = _materialize()
    mutations: tuple[Callable[[dict[str, object]], None], ...] = (
        lambda value: value["spec"]["template"]["spec"].__setitem__(  # type: ignore[index]
            "nodeSelector", {"fdai.io/pool": "other"}
        ),
        lambda value: value["spec"]["template"]["spec"]["containers"][0][  # type: ignore[index]
            "resources"
        ]["limits"].__setitem__("memory", "2Gi"),
        lambda value: value["spec"]["template"]["spec"]["containers"][0].__setitem__(  # type: ignore[index]
            "envFrom", [{"configMapRef": {"name": "unreviewed"}}]
        ),
        lambda value: value["spec"]["template"]["spec"]["containers"][0].__setitem__(  # type: ignore[index]
            "restartPolicy", "Always"
        ),
        lambda value: (
            value["spec"]["template"]["metadata"]
            .setdefault(  # type: ignore[index,union-attr]
                "annotations", {}
            )
            .__setitem__("sidecar.istio.io/inject", "true")
        ),
        lambda value: value["spec"]["template"]["spec"]["volumes"][0]["csi"][  # type: ignore[index]
            "volumeAttributes"
        ].__setitem__("secretProviderClass", "other"),
    )
    for mutate in mutations:
        changed = copy.deepcopy(expected.manifest)
        mutate(changed)
        with pytest.raises(ValueError, match="controlled contract"):
            validate_existing_job(changed, expected=expected)


def test_rejects_changed_identity_and_secret_override() -> None:
    changed = _cronjob()
    changed["spec"]["jobTemplate"]["spec"]["template"]["spec"][  # type: ignore[index]
        "serviceAccountName"
    ] = "executor"
    changed_digest = protected_cronjob_template_digest(
        _scheduled_job(),
        template_name="inventory",
        namespace="fdai-runtime",
        source_revision=_REVISION,
    )
    with pytest.raises(ValueError, match="protected template digest"):
        materialize_cronjob_execution(
            changed,
            purpose="inventory",
            source_revision=_REVISION,
            target_binding=_TARGET,
            expected_template_name="inventory",
            expected_container_name="inventory",
            expected_image=_IMAGE,
            expected_command=("python", "-m", "fdai.delivery.inventory_sync_cli"),
            expected_service_account="inventory-job",
            args=("--initial",),
            protected_template_digest=changed_digest,
            protected_identity_binding_digest=_IDENTITY_BINDING_DIGEST,
        )

    with pytest.raises(ValueError, match="non-secret"):
        materialize_cronjob_execution(
            _cronjob(),
            purpose="inventory",
            source_revision=_REVISION,
            target_binding=_TARGET,
            expected_template_name="inventory",
            expected_container_name="inventory",
            expected_image=_IMAGE,
            expected_command=("python", "-m", "fdai.delivery.inventory_sync_cli"),
            expected_service_account="inventory-job",
            args=("--initial",),
            environment={"ACCESS_TOKEN": "not-allowed"},
            protected_template_digest=_template_digest(),
            protected_identity_binding_digest=_IDENTITY_BINDING_DIGEST,
        )


def test_terminal_state_requires_failed_condition_or_exhausted_backoff() -> None:
    assert (
        job_terminal_state(
            {
                "spec": {"backoffLimit": 1},
                "status": {
                    "failed": 1,
                    "conditions": [],
                },
            }
        )
        == "running"
    )
    assert (
        job_terminal_state(
            {
                "spec": {"backoffLimit": 1},
                "status": {
                    "failed": 2,
                    "conditions": [],
                },
            }
        )
        == "failed"
    )
    assert (
        job_terminal_state(
            {
                "status": {
                    "failed": 1,
                    "conditions": [{"type": "Failed", "status": "True"}],
                }
            }
        )
        == "failed"
    )
    with pytest.raises(ValueError, match="conditions conflict"):
        job_terminal_state(
            {
                "status": {
                    "succeeded": 1,
                    "conditions": [
                        {"type": "Complete", "status": "True"},
                        {"type": "Failed", "status": "True"},
                    ],
                }
            }
        )


def _materialize_inventory(cronjob: dict[str, object]) -> object:
    return materialize_cronjob_execution(
        cronjob,
        purpose="inventory",
        source_revision=_REVISION,
        target_binding=_TARGET,
        expected_template_name="inventory",
        expected_container_name="inventory",
        expected_image=_IMAGE,
        expected_command=("python", "-m", "fdai.delivery.inventory_sync_cli"),
        expected_service_account="inventory-job",
        args=("--initial",),
        require_suspended=False,
        protected_template_digest=_template_digest(),
        protected_identity_binding_digest=_IDENTITY_BINDING_DIGEST,
    )


def _with_materialized_defaults(cronjob: dict[str, object]) -> dict[str, object]:
    changed = copy.deepcopy(cronjob)
    container = _container(changed)
    container["securityContext"]["privileged"] = False  # type: ignore[index]
    container["securityContext"]["readOnlyRootFilesystem"] = False  # type: ignore[index]
    container["volumeMounts"][0]["mountPropagation"] = "None"  # type: ignore[index]
    _environment(changed, "FDAI_INVENTORY_DSN")["valueFrom"]["secretKeyRef"]["optional"] = False  # type: ignore[index]
    pod = changed["spec"]["jobTemplate"]["spec"]["template"]["spec"]  # type: ignore[index]
    pod["volumes"][0]["csi"]["fsType"] = ""  # type: ignore[index]
    return changed


def test_accepts_kubernetes_defaults_materialized_by_the_provider() -> None:
    live = _with_materialized_defaults(_cronjob())

    first = _materialize_inventory(live)
    second = _materialize_inventory(copy.deepcopy(live))

    annotations = first.manifest["metadata"]["annotations"]  # type: ignore[attr-defined]
    assert annotations["fdai.io/template-digest"] == _template_digest()
    assert first.execution_digest == second.execution_digest  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: _container(value)["securityContext"].__setitem__("privileged", True),
        lambda value: _container(value)["securityContext"].__setitem__(
            "readOnlyRootFilesystem", True
        ),
        lambda value: _container(value)["volumeMounts"][0].__setitem__(
            "mountPropagation", "HostToContainer"
        ),
        lambda value: _environment(value, "FDAI_INVENTORY_DSN")["valueFrom"][
            "secretKeyRef"
        ].__setitem__("optional", True),
        lambda value: value["spec"]["jobTemplate"]["spec"]["template"]["spec"]["volumes"][0][
            "csi"
        ].__setitem__("fsType", "ext4"),
    ),
    ids=("privileged", "read-only-root", "mount-propagation", "optional-secret", "csi-fs-type"),
)
def test_rejects_non_default_values_of_normalized_fields(
    mutate: Callable[[dict[str, object]], None],
) -> None:
    changed = _with_materialized_defaults(_cronjob())
    mutate(changed)

    with pytest.raises(ValueError, match="protected template digest"):
        _materialize_inventory(changed)


def test_projection_leaves_the_protected_contract_unchanged() -> None:
    import fdai_deployment_cli.aks_job_execution as execution

    captured: list[object] = []
    original = execution._digest  # noqa: SLF001

    def capture(value: object) -> str:
        captured.append(value)
        return original(value)

    execution._digest = capture  # type: ignore[assignment]  # noqa: SLF001
    try:
        _template_digest()
    finally:
        execution._digest = original  # noqa: SLF001

    protected = captured[-1]
    assert execution._cronjob_contract(protected) == protected  # type: ignore[arg-type]  # noqa: SLF001


def test_existing_job_without_an_empty_env_value_keeps_the_same_contract() -> None:
    from fdai_deployment_cli.aks_job_execution import validate_existing_job

    expected = _materialize()
    existing = copy.deepcopy(expected.manifest)  # type: ignore[attr-defined]
    container = existing["spec"]["template"]["spec"]["containers"][0]
    entry = next(item for item in container["env"] if item.get("value") == "")
    del entry["value"]

    validate_existing_job(existing, expected=expected)  # type: ignore[arg-type]

    entry["value"] = "Microsoft.Compute/virtualMachines"
    with pytest.raises(ValueError, match="controlled contract changed"):
        validate_existing_job(existing, expected=expected)  # type: ignore[arg-type]

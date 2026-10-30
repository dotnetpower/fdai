"""Own only disposable CI resources. Registration removal never authorizes killing running work."""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Callable
from typing import Any

from scripts.automation.runner_controller.azure import AzureAPI
from scripts.automation.runner_controller.config import Settings
from scripts.automation.runner_controller.transport import ProviderError


class Workers:
    def __init__(
        self,
        settings: Settings,
        azure: AzureAPI,
        ensure_authority: Callable[[], None] | None = None,
    ) -> None:
        self.settings = settings
        self.azure = azure
        self.ensure_authority = ensure_authority

    def _effect_checkpoint(self) -> None:
        if self.ensure_authority is None:
            raise ValueError("provider effects require an active controller lease")
        self.ensure_authority()

    def _resource(self, kind: str, name: str) -> str:
        if not name.startswith(self.settings.name_prefix + "-"):
            raise ValueError("worker resource is outside the controller's owned prefix")
        return (
            f"/subscriptions/{self.settings.subscription_id}/resourceGroups/"
            f"{self.settings.resource_group}/providers/{kind}/{name}"
        )

    def check_ownership(self) -> None:
        for job in self.settings.jobs.values():
            path = (
                f"/subscriptions/{self.settings.subscription_id}/resourceGroups/"
                f"{self.settings.resource_group}/providers/Microsoft.App/jobs/{job}"
            )
            actual = self.azure.get_resource(path)
            configuration = actual["properties"]["configuration"]
            if configuration["triggerType"] != "Manual":
                raise ValueError("worker job still has another scaler; refusing dual ownership")
            manual = configuration["manualTriggerConfig"]
            if any(
                type(manual.get(field)) is not int or manual[field] != 1
                for field in ("parallelism", "replicaCompletionCount")
            ):
                raise ValueError("one start reservation must create exactly one worker replica")
            if (
                type(configuration.get("replicaRetryLimit")) is not int
                or configuration["replicaRetryLimit"] != 0
                or configuration.get("replicaTimeout") != 86400
            ):
                raise ValueError(
                    "worker retries or execution lifetime differ from the approved shape"
                )
            containers = actual["properties"]["template"]["containers"]
            if (
                len(containers) != 1
                or containers[0]["name"] != "runner"
                or containers[0]["image"] != self.settings.worker_image
            ):
                raise ValueError(
                    "worker template differs from the approved single-container digest"
                )

    def start(self, worker: dict[str, Any], ticket: str) -> str:
        bootstrap = {
            "controller_url": self.settings.controller_url.rstrip("/"),
            "worker_id": worker["id"],
            "ticket": ticket,
        }
        if worker["pool"] != "docker":
            cpu = 1 if worker["pool"] == "control" else 4
            self._effect_checkpoint()
            return self.azure.start_container(
                self.settings.jobs[worker["pool"]],
                {
                    "containers": [
                        {
                            "name": "runner",
                            "image": self.settings.worker_image,
                            "command": [
                                "/usr/bin/tini",
                                "-g",
                                "--",
                                "/usr/bin/python3",
                                "/opt/fdai-ci/broker-entrypoint.py",
                            ],
                            "resources": {"cpu": cpu, "memory": f"{cpu * 2}Gi"},
                            "env": [
                                {"name": "FDAI_RUNNER_BOOTSTRAP", "value": json.dumps(bootstrap)},
                                {"name": "FDAI_RUNNER_ID", "value": worker["id"]},
                            ],
                        }
                    ]
                },
            )
        if not self.settings.vm_image_id or not self.settings.vm_subnet_id:
            raise ValueError("Docker pool has no approved baked image or isolated subnet")
        name = worker["name"]
        if not isinstance(name, str):
            raise ValueError("worker name must be a string")
        nic_path = self._resource("Microsoft.Network/networkInterfaces", name)
        self._effect_checkpoint()
        self.azure.put_resource(
            nic_path,
            {
                "location": self.settings.location,
                "tags": {"fdai:purpose": "ephemeral-ci", "fdai:worker": worker["id"]},
                "properties": {
                    "ipConfigurations": [
                        {
                            "name": "private",
                            "properties": {
                                "subnet": {"id": self.settings.vm_subnet_id},
                                "privateIPAllocationMethod": "Dynamic",
                            },
                        }
                    ]
                },
            },
            api_version="2024-05-01",
        )
        deadline = time.monotonic() + 30
        while True:
            nic = self.azure.get_resource(nic_path, api_version="2024-05-01")
            self._verify_identity(worker, nic)
            phase = nic["properties"]["provisioningState"]
            if phase == "Succeeded":
                break
            if phase in {"Failed", "Canceled"} or time.monotonic() >= deadline:
                raise ProviderError("worker_nic_not_ready")
            time.sleep(1)
        # The short, single-use bootstrap ticket is not a PAT or an Azure credential.
        cloud_config = "#cloud-config\n" + json.dumps(
            {
                "write_files": [
                    {
                        "path": "/etc/fdai-ci-bootstrap.json",
                        "owner": "root:root",
                        "permissions": "0600",
                        "content": json.dumps(bootstrap),
                    }
                ],
                "runcmd": [
                    [
                        "systemd-run",
                        "--unit=fdai-ci-worker",
                        "--collect",
                        "/bin/bash",
                        "-c",
                        (
                            "/usr/bin/python3 /opt/fdai-ci/broker-entrypoint.py "
                            "--config /etc/fdai-ci-bootstrap.json; status=$?; "
                            '/usr/bin/systemctl poweroff; exit "$status"'
                        ),
                    ]
                ],
            }
        )
        vm_path = self._resource("Microsoft.Compute/virtualMachines", name)
        self._effect_checkpoint()
        self.azure.put_resource(
            vm_path,
            {
                "location": self.settings.location,
                "tags": {"fdai:purpose": "ephemeral-ci", "fdai:worker": worker["id"]},
                "properties": {
                    "hardwareProfile": {"vmSize": self.settings.vm_size},
                    "storageProfile": {
                        "imageReference": {"id": self.settings.vm_image_id},
                        "osDisk": {
                            "createOption": "FromImage",
                            "deleteOption": "Delete",
                            "managedDisk": {"storageAccountType": "Premium_LRS"},
                        },
                    },
                    "osProfile": {
                        "computerName": name[:64],
                        "adminUsername": "ciadmin",
                        "customData": base64.b64encode(cloud_config.encode()).decode(),
                        "linuxConfiguration": {
                            "disablePasswordAuthentication": True,
                            "ssh": {
                                "publicKeys": [
                                    {
                                        "path": "/home/ciadmin/.ssh/authorized_keys",
                                        "keyData": self.settings.ssh_public_key,
                                    }
                                ]
                            },
                        },
                    },
                    "networkProfile": {
                        "networkInterfaces": [
                            {
                                "id": nic_path,
                                "properties": {"deleteOption": "Delete"},
                            }
                        ]
                    },
                    "securityProfile": {
                        "securityType": "TrustedLaunch",
                        "uefiSettings": {"secureBootEnabled": True, "vTpmEnabled": True},
                    },
                },
            },
            api_version="2024-07-01",
        )
        return name

    def recover_reference(self, worker: dict[str, Any]) -> str | None:
        """Recover an accepted start by readback, never by repeating the start request."""
        if worker["pool"] == "docker":
            try:
                actual = self.azure.get_resource(
                    self._resource("Microsoft.Compute/virtualMachines", worker["name"]),
                    api_version="2024-07-01",
                )
            except ProviderError as error:
                if error.status == 404:
                    return None
                raise
            self._verify_identity(worker, actual)
            return str(worker["name"])
        job = self.settings.jobs[worker["pool"]]
        found = []
        for execution in self.azure.container_executions(job):
            template = execution.get("properties", {}).get("template")
            if template is None:
                execution = self.azure.container_execution(job, execution["name"])
                template = execution["properties"].get("template", {})
            if any(
                item.get("name") == "FDAI_RUNNER_ID" and item.get("value") == worker["id"]
                for container in template.get("containers", [])
                for item in container.get("env", [])
            ):
                found.append(execution["name"])
        if len(found) > 1:
            raise ValueError("multiple provider executions match one start reservation")
        return found[0] if found else None

    @staticmethod
    def _verify_identity(worker: dict[str, Any], actual: dict[str, Any]) -> None:
        if actual.get("tags", {}).get("fdai:worker") != worker["id"]:
            raise ValueError("resource readback does not match the reserved worker identity")

    def terminal(self, worker: dict[str, Any]) -> bool:
        if worker.get("cleanup_requested") and worker.get("terminal_observed_at"):
            return True
        if not worker.get("provider_ref"):
            return False
        if worker["pool"] == "docker":
            if worker.get("listener_exit_code") is not None:
                return True
            try:
                view = self.azure.get_resource(
                    self._resource("Microsoft.Compute/virtualMachines", worker["name"])
                    + "/instanceView",
                    api_version="2024-07-01",
                )
            except ProviderError as error:
                if error.status == 404:
                    return False
                raise
            # The guest powers off after launcher exit, including failure before registration.
            # No idle or busy timer stops it. Provider power readback can recover a lost callback.
            return any(
                status.get("code") in {"PowerState/stopped", "PowerState/deallocated"}
                for status in view.get("statuses", [])
            )
        try:
            value = self.azure.container_execution(
                self.settings.jobs[worker["pool"]], worker["provider_ref"]
            )
        except ProviderError as error:
            if error.status == 404:
                return False
            raise
        return value["properties"]["status"] in {"Succeeded", "Failed", "Stopped"}

    def cleanup(self, worker: dict[str, Any]) -> None:
        if worker["pool"] != "docker":
            return
        if not self.terminal(worker):
            raise ValueError("refusing to delete a VM without terminal listener or power evidence")
        try:
            actual = self.azure.get_resource(
                self._resource("Microsoft.Compute/virtualMachines", worker["name"]),
                api_version="2024-07-01",
            )
            self._verify_identity(worker, actual)
            if actual["properties"]["provisioningState"] == "Deleting":
                return
            self._effect_checkpoint()
            self.azure.delete_resource(
                self._resource("Microsoft.Compute/virtualMachines", worker["name"]),
                api_version="2024-07-01",
            )
        except ProviderError as error:
            if error.status != 404:
                raise

    def absent(self, worker: dict[str, Any]) -> bool:
        vm = self._resource("Microsoft.Compute/virtualMachines", worker["name"])
        nic = self._resource("Microsoft.Network/networkInterfaces", worker["name"])
        try:
            actual_vm = self.azure.get_resource(vm, api_version="2024-07-01")
            self._verify_identity(worker, actual_vm)
            return False
        except ProviderError as error:
            if error.status != 404:
                raise
        try:
            actual_nic = self.azure.get_resource(nic, api_version="2024-05-01")
        except ProviderError as error:
            if error.status == 404:
                return True
            raise
        self._verify_identity(worker, actual_nic)
        self._effect_checkpoint()
        self.azure.delete_resource(nic, api_version="2024-05-01")
        return False

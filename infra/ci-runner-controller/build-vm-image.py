#!/usr/bin/env python3
"""Prepare or explicitly build a credential-free Trusted Launch Gallery image version.

The caller approves the exact subscription, existing group/subnet, new resource
names, base image and published source commit. Default mode only prepares local
cloud-init. --execute permits effects on these new builder resources, never an
existing VM. Azure Run Command is used only by the operator on that new builder;
the controller and workers receive no such permission. An ambiguous command stops
the attempt without retries or speculative deletion. Keep failed builders for
separately approved diagnosis/cleanup.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SOURCE_FILES = (
    "infra/ci-runner/toolchain.json",
    "infra/ci-runner/verify-toolchain.py",
    "infra/ci-runner/provision-toolchain.sh",
    "infra/ci-runner-aca/broker-entrypoint.py",
    "infra/ci-runner-controller/provision-vm-image.sh",
)
UUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
NAME = r"[a-z][a-z0-9-]{1,61}[a-z0-9]"
SOURCE_ROOT = "/opt/fdai-ci/image-source"


class BuildError(Exception):
    """Nonsecret failure classification, without provider output."""


def command(args: list[str], timeout: float) -> str:
    try:
        result = subprocess.run(  # noqa: S603 - Fixed executables/verbs and validated inputs.
            args,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        raise BuildError("command_failed_or_timed_out") from None
    if result.returncode:
        raise BuildError("command_failed_no_retry")
    try:
        return result.stdout.decode("utf-8")
    except UnicodeError:
        raise BuildError("invalid_command_output") from None


def validate(args: argparse.Namespace) -> str:
    if not re.fullmatch(UUID, args.subscription_id):
        raise BuildError("invalid_subscription")
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_sha):
        raise BuildError("source_sha_must_be_full_commit")
    for name in (args.builder_name, args.nic_name, args.disk_name, args.image_definition):
        if not re.fullmatch(NAME, name):
            raise BuildError("invalid_explicit_resource_name")
    if not re.fullmatch(r"[a-z][a-z0-9_.-]{1,78}[a-z0-9_]", args.gallery_name):
        raise BuildError("invalid_gallery_name")
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", args.image_version):
        raise BuildError("exact_gallery_version_required")
    if any(int(part) > 2147483647 for part in args.image_version.split(".")):
        raise BuildError("gallery_version_component_out_of_range")
    if not re.fullmatch(r"[A-Za-z0-9_().-]{1,90}", args.resource_group):
        raise BuildError("invalid_resource_group")
    if not re.fullmatch(r"[a-z][a-z0-9]+", args.location):
        raise BuildError("invalid_location")
    if not re.fullmatch(
        rf"/subscriptions/{UUID}/resourceGroups/[^/]+/providers/Microsoft.Network/"
        r"virtualNetworks/[^/]+/subnets/[^/]+",
        args.subnet_id,
        re.IGNORECASE,
    ) or not args.subnet_id.lower().startswith(f"/subscriptions/{args.subscription_id.lower()}/"):
        raise BuildError("invalid_ci_subnet")
    arm_image = re.fullmatch(
        rf"/subscriptions/{UUID}/resourceGroups/[^/]+/providers/Microsoft.Compute/"
        r"galleries/[^/]+/images/[^/]+/versions/[0-9]+\.[0-9]+\.[0-9]+",
        args.base_image_id,
        re.IGNORECASE,
    )
    marketplace = re.fullmatch(
        r"Canonical:ubuntu-24_04-lts:[A-Za-z0-9_.-]+:[0-9]+(?:\.[0-9]+)+",
        args.base_image_id,
    )
    if arm_image is None and marketplace is None:
        raise BuildError("base_image_requires_exact_ubuntu_image_reference")
    if not re.fullmatch(r"Standard_[A-Za-z0-9_]+", args.vm_size):
        raise BuildError("invalid_vm_size")
    try:
        public_key = args.ssh_public_key_file.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        raise BuildError("ssh_public_key_unavailable") from None
    if not re.fullmatch(r"(ssh-ed25519|ssh-rsa) [A-Za-z0-9+/]+={0,3}( [^\r\n]+)?", public_key):
        raise BuildError("public_ssh_key_required")
    return public_key


def prepare(args: argparse.Namespace, public_key: str) -> Path:
    """Read only the exact committed files; never archive a dirty checkout or credentials."""
    git = shutil.which("git")
    if git is None:
        raise BuildError("git_unavailable")
    if command([git, "cat-file", "-t", args.source_sha], 30).strip() != "commit":
        raise BuildError("source_sha_must_identify_commit")
    files = []
    for relative in SOURCE_FILES:
        content = command([git, "show", f"{args.source_sha}:{relative}"], 30)
        files.append(
            {
                "path": f"{SOURCE_ROOT}/{relative}",
                "owner": "root:root",
                "permissions": "0600",
                "encoding": "b64",
                "content": base64.b64encode(content.encode()).decode("ascii"),
            }
        )
    payload = {
        "write_files": files,
        "runcmd": [
            [
                "timeout",
                "3600",
                "bash",
                f"{SOURCE_ROOT}/infra/ci-runner-controller/provision-vm-image.sh",
                SOURCE_ROOT,
                args.source_sha,
            ]
        ],
    }
    try:
        args.state_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
        path = args.state_dir / "builder-cloud-init.json"
        path.write_text("#cloud-config\n" + json.dumps(payload), encoding="utf-8")
        path.chmod(0o600)
        (args.state_dir / "source.json").write_text(
            json.dumps(
                {
                    "source_sha": args.source_sha,
                    "base_image_id": args.base_image_id,
                    "gallery_name": args.gallery_name,
                    "image_definition": args.image_definition,
                    "image_version": args.image_version,
                    "ssh_public_key": public_key,
                }
            ),
            encoding="utf-8",
        )
    except OSError:
        raise BuildError("use_new_private_state_directory") from None
    return path


class Builder:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.cli = shutil.which("az")
        if self.cli is None:
            raise BuildError("azure_cli_unavailable")
        self.deadline = time.monotonic() + 7200
        self.root = f"/subscriptions/{args.subscription_id}/resourceGroups/{args.resource_group}"
        self.ids = {
            "vm": f"{self.root}/providers/Microsoft.Compute/virtualMachines/{args.builder_name}",
            "nic": f"{self.root}/providers/Microsoft.Network/networkInterfaces/{args.nic_name}",
            "disk": f"{self.root}/providers/Microsoft.Compute/disks/{args.disk_name}",
            "gallery": f"{self.root}/providers/Microsoft.Compute/galleries/{args.gallery_name}",
        }
        self.ids["definition"] = f"{self.ids['gallery']}/images/{args.image_definition}"
        self.ids["image"] = f"{self.ids['definition']}/versions/{args.image_version}"
        self.tags = ["fdai:image-builder=true", f"fdai:source-sha={args.source_sha}"]

    def az(self, stage: str, *argv: str, timeout: int = 600) -> Any:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise BuildError("total_deadline_exceeded")
        print(json.dumps({"stage": stage, "status": "started"}), flush=True)
        text = command(
            [
                self.cli,
                *argv,
                "--subscription",
                self.args.subscription_id,
                "--only-show-errors",
                "--output",
                "json",
            ],
            min(remaining, timeout),
        )
        print(json.dumps({"stage": stage, "status": "returned"}), flush=True)
        try:
            return json.loads(text) if text.strip() else None
        except ValueError:
            raise BuildError("invalid_provider_response") from None

    def resources(self) -> dict[str, dict[str, Any]]:
        result = self.az(
            "read_scope", "resource", "list", "--resource-group", self.args.resource_group
        )
        if not isinstance(result, list) or not all(isinstance(item, dict) for item in result):
            raise BuildError("invalid_scope_inventory")
        return {str(item.get("id", "")).lower(): item for item in result}

    def run_script(self, stage: str, script: str, marker: str) -> None:
        result = self.az(
            stage,
            "vm",
            "run-command",
            "invoke",
            "--ids",
            self.ids["vm"],
            "--command-id",
            "RunShellScript",
            "--scripts",
            script,
            timeout=3900,
        )
        values = result.get("value", []) if isinstance(result, dict) else []
        if not any(
            item.get("code")
            in {
                "ProvisioningState/succeeded",
                "ComponentStatus/StdOut/succeeded",
            }
            and marker in str(item.get("message", "")).splitlines()
            for item in values
            if isinstance(item, dict)
        ):
            raise BuildError("builder_stage_unconfirmed")

    def execute(self, payload: Path, public_key: str) -> str:
        args = self.args
        existing = self.resources()
        if any(self.ids[kind].lower() in existing for kind in ("vm", "nic", "disk", "image")):
            raise BuildError("existing_builder_resource_refused")
        self.prepare_gallery(existing)
        self.az(
            "create_nic",
            "network",
            "nic",
            "create",
            "--resource-group",
            args.resource_group,
            "--name",
            args.nic_name,
            "--location",
            args.location,
            "--subnet",
            args.subnet_id,
            "--tags",
            *self.tags,
        )
        self.az(
            "create_vm",
            "vm",
            "create",
            "--resource-group",
            args.resource_group,
            "--name",
            args.builder_name,
            "--location",
            args.location,
            "--image",
            args.base_image_id,
            "--nics",
            self.ids["nic"],
            "--os-disk-name",
            args.disk_name,
            "--os-disk-size-gb",
            "256",
            "--size",
            args.vm_size,
            "--admin-username",
            "imagebuilder",
            "--ssh-key-values",
            public_key,
            "--custom-data",
            str(payload),
            "--security-type",
            "TrustedLaunch",
            "--enable-secure-boot",
            "true",
            "--enable-vtpm",
            "true",
            "--os-disk-delete-option",
            "Delete",
            "--nic-delete-option",
            "Delete",
            "--tags",
            *self.tags,
            timeout=900,
        )
        self.verify_builder()
        self.az(
            "tag_disk",
            "tag",
            "update",
            "--resource-id",
            self.ids["disk"],
            "--operation",
            "Merge",
            "--tags",
            *self.tags,
        )
        self.run_script(
            "wait_cloud_init",
            "set -eu; timeout 3600 cloud-init status --wait >/dev/null; "
            f"grep -q '{args.source_sha}' /var/lib/fdai-ci-image-ready; "
            "test ! -e /opt/actions-runner/.runner; test ! -e /opt/actions-runner/.credentials; "
            "systemctl is-active --quiet docker; echo fdai_image_ready",
            "fdai_image_ready",
        )
        self.run_script(
            "deprovision",
            "set -eu; cloud-init clean --logs --machine-id --seed; "
            "waagent -deprovision+user -force >/dev/null; echo fdai_image_deprovisioned",
            "fdai_image_deprovisioned",
        )
        self.az("deallocate", "vm", "deallocate", "--ids", self.ids["vm"])
        self.az("generalize", "vm", "generalize", "--ids", self.ids["vm"])
        self.az(
            "capture_image",
            "sig",
            "image-version",
            "create",
            "--resource-group",
            args.resource_group,
            "--gallery-name",
            args.gallery_name,
            "--gallery-image-definition",
            args.image_definition,
            "--gallery-image-version",
            args.image_version,
            "--virtual-machine",
            self.ids["vm"],
            "--location",
            args.location,
            "--target-regions",
            args.location,
            "--replica-count",
            "1",
            "--storage-account-type",
            "Standard_LRS",
            "--replication-mode",
            "Full",
            "--exclude-from-latest",
            "true",
            "--tags",
            *self.tags,
            timeout=900,
        )
        image = self.az(
            "verify_image",
            "sig",
            "image-version",
            "show",
            "--resource-group",
            args.resource_group,
            "--gallery-name",
            args.gallery_name,
            "--gallery-image-definition",
            args.image_definition,
            "--gallery-image-version",
            args.image_version,
            "--expand",
            "ReplicationStatus",
        )
        source = (
            image.get("storageProfile", {}).get("source", {}) if isinstance(image, dict) else {}
        )
        source_vm = source.get("virtualMachineId") or source.get("id", "")
        if not isinstance(image, dict) or (
            str(image.get("id", "")).lower() != self.ids["image"].lower()
            or image.get("provisioningState") != "Succeeded"
            or str(source_vm).lower() != self.ids["vm"].lower()
            or image.get("replicationStatus", {}).get("aggregatedState") != "Completed"
            or image.get("publishingProfile", {}).get("replicationMode") != "Full"
            or image.get("publishingProfile", {}).get("excludeFromLatest") is not True
        ):
            raise BuildError("captured_image_unconfirmed")
        self.verify_definition()
        self.verify_builder()
        self.az("delete_builder", "vm", "delete", "--ids", self.ids["vm"], "--yes")
        remaining = self.resources()
        for kind in ("nic", "disk"):
            item = remaining.get(self.ids[kind].lower())
            if item is not None:
                self.owned(item)
                self.az(f"delete_{kind}", "resource", "delete", "--ids", self.ids[kind])
        final_resources = self.resources()
        if any(self.ids[kind].lower() in final_resources for kind in ("vm", "nic", "disk")):
            raise BuildError("builder_cleanup_unconfirmed")
        return self.ids["image"]

    def prepare_gallery(self, existing: dict[str, dict[str, Any]]) -> None:
        args = self.args
        if self.ids["gallery"].lower() not in existing:
            self.az(
                "create_gallery",
                "sig",
                "create",
                "--resource-group",
                args.resource_group,
                "--gallery-name",
                args.gallery_name,
                "--location",
                args.location,
                "--tags",
                *self.tags,
            )
        gallery = self.az(
            "verify_gallery",
            "sig",
            "show",
            "--resource-group",
            args.resource_group,
            "--gallery-name",
            args.gallery_name,
        )
        if not isinstance(gallery, dict) or (
            str(gallery.get("id", "")).lower() != self.ids["gallery"].lower()
            or gallery.get("location") != args.location
            or (gallery.get("sharingProfile") or {}).get("permissions") not in (None, "Private")
        ):
            raise BuildError("gallery_scope_or_sharing_changed")
        definitions = self.az(
            "list_definitions",
            "sig",
            "image-definition",
            "list",
            "--resource-group",
            args.resource_group,
            "--gallery-name",
            args.gallery_name,
        )
        if not isinstance(definitions, list) or not all(
            isinstance(item, dict) for item in definitions
        ):
            raise BuildError("invalid_gallery_inventory")
        if not any(
            item.get("id", "").lower() == self.ids["definition"].lower() for item in definitions
        ):
            self.az(
                "create_definition",
                "sig",
                "image-definition",
                "create",
                "--resource-group",
                args.resource_group,
                "--gallery-name",
                args.gallery_name,
                "--gallery-image-definition",
                args.image_definition,
                "--location",
                args.location,
                "--publisher",
                "fdai",
                "--offer",
                "ci-runner",
                "--sku",
                "ubuntu-24-04",
                "--os-type",
                "Linux",
                "--os-state",
                "Generalized",
                "--architecture",
                "x64",
                "--hyper-v-generation",
                "V2",
                "--features",
                "SecurityType=TrustedLaunch",
                "--tags",
                *self.tags,
            )
        self.verify_definition()
        versions = self.az(
            "list_versions",
            "sig",
            "image-version",
            "list",
            "--resource-group",
            args.resource_group,
            "--gallery-name",
            args.gallery_name,
            "--gallery-image-definition",
            args.image_definition,
        )
        if not isinstance(versions, list) or not all(isinstance(item, dict) for item in versions):
            raise BuildError("invalid_gallery_inventory")
        if any(item.get("id", "").lower() == self.ids["image"].lower() for item in versions):
            raise BuildError("existing_gallery_version_refused")

    def verify_definition(self) -> None:
        definition = self.az(
            "verify_definition",
            "sig",
            "image-definition",
            "show",
            "--resource-group",
            self.args.resource_group,
            "--gallery-name",
            self.args.gallery_name,
            "--gallery-image-definition",
            self.args.image_definition,
        )
        if not isinstance(definition, dict) or (
            str(definition.get("id", "")).lower() != self.ids["definition"].lower()
            or definition.get("hyperVGeneration") != "V2"
            or definition.get("architecture") != "x64"
            or definition.get("osType") != "Linux"
            or definition.get("osState") != "Generalized"
            or [
                feature.get("value")
                for feature in (definition.get("features") or [])
                if isinstance(feature, dict) and feature.get("name") == "SecurityType"
            ]
            != ["TrustedLaunch"]
        ):
            raise BuildError("trusted_launch_definition_required")

    def owned(self, resource: dict[str, Any]) -> None:
        tags = resource.get("tags", {})
        if (
            tags.get("fdai:image-builder") != "true"
            or tags.get("fdai:source-sha") != self.args.source_sha
        ):
            raise BuildError("builder_ownership_changed")

    def verify_builder(self) -> None:
        vm = self.az("verify_builder", "vm", "show", "--ids", self.ids["vm"])
        if not isinstance(vm, dict) or str(vm.get("id", "")).lower() != self.ids["vm"].lower():
            raise BuildError("builder_identity_changed")
        self.owned(vm)
        nics = vm.get("networkProfile", {}).get("networkInterfaces", [])
        disk = vm.get("storageProfile", {}).get("osDisk", {}).get("managedDisk", {}).get("id", "")
        if (
            vm.get("identity") not in (None, {})
            or [str(item.get("id", "")).lower() for item in nics] != [self.ids["nic"].lower()]
            or str(disk).lower() != self.ids["disk"].lower()
            or vm.get("storageProfile", {}).get("dataDisks", [])
            or vm.get("securityProfile", {}).get("securityType") != "TrustedLaunch"
            or vm.get("securityProfile", {}).get("uefiSettings", {}).get("secureBootEnabled")
            is not True
            or vm.get("securityProfile", {}).get("uefiSettings", {}).get("vTpmEnabled") is not True
        ):
            raise BuildError("builder_scope_changed")
        nic = self.az("verify_private_nic", "network", "nic", "show", "--ids", self.ids["nic"])
        if not isinstance(nic, dict) or str(nic.get("id", "")).lower() != self.ids["nic"].lower():
            raise BuildError("builder_scope_changed")
        self.owned(nic)
        ip_configs = nic.get("ipConfigurations", [])
        if (
            not isinstance(ip_configs, list)
            or len(ip_configs) != 1
            or (
                ip_configs[0].get("publicIPAddress")
                or ip_configs[0].get("subnet", {}).get("id", "").lower()
                != self.args.subnet_id.lower()
            )
        ):
            raise BuildError("builder_network_changed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "subscription-id",
        "resource-group",
        "location",
        "subnet-id",
        "source-sha",
        "base-image-id",
        "builder-name",
        "nic-name",
        "disk-name",
        "gallery-name",
        "image-definition",
        "image-version",
    ):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--ssh-public-key-file", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--vm-size", default="Standard_D4ds_v4")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    try:
        public_key = validate(args)
        payload = prepare(args, public_key)
        image_id = Builder(args).execute(payload, public_key) if args.execute else None
    except BuildError as error:
        print(json.dumps({"status": "stopped", "reason": str(error)}), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "image_captured_and_builder_removed"
                if args.execute
                else "prepared_no_azure_effects",
                "image_id": image_id,
                "source_sha": args.source_sha,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

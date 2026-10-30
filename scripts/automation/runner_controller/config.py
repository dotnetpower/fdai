"""Validate operator-selected CI scope, never workflow-supplied resource names."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from scripts.automation.runner_pool_policy import PoolPolicy


@dataclass(frozen=True)
class Settings:
    repository: str
    name_prefix: str
    subscription_id: str
    resource_group: str
    jobs: dict[str, str]
    worker_image: str
    controller_url: str
    location: str
    vm_subnet_id: str
    vm_image_id: str
    vm_size: str
    ssh_public_key: str
    storage_url: str
    storage_container: str
    storage_blob: str
    cpu_budgets: dict[str, int]
    apply: bool = False
    interval_seconds: int = 15

    @classmethod
    def load(cls, raw: str, *, apply: bool, hostname: str = "") -> Settings:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("controller configuration must be an object")
        data["apply"] = apply
        if "controller_url" not in data or data["controller_url"] == "":
            data["controller_url"] = f"https://{hostname}" if hostname else ""
        settings = cls(**data)
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", settings.repository):
            raise ValueError("controller repository must be owner/repository")
        if not re.fullmatch(r"[a-z][a-z0-9-]{2,23}", settings.name_prefix):
            raise ValueError("controller name prefix must be a short lowercase resource prefix")
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", settings.subscription_id):
            raise ValueError("controller requires one subscription identity")
        if not re.fullmatch(r"[A-Za-z0-9._()-]{1,90}", settings.resource_group):
            raise ValueError("controller requires one worker resource group")
        if set(settings.jobs) != {"control", "general"} or any(
            not re.fullmatch(r"[a-z][a-z0-9-]{1,31}", name) for name in settings.jobs.values()
        ):
            raise ValueError("controller requires explicit manual control and general jobs")
        if not re.fullmatch(
            r"[a-z0-9.-]+/[a-z0-9._/-]+@sha256:[0-9a-f]{64}", settings.worker_image
        ):
            raise ValueError("worker image must be an immutable registry digest")
        parsed = urlsplit(settings.controller_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("bootstrap requires an operator-selected HTTPS controller origin")
        if type(settings.interval_seconds) is not int or not 5 <= settings.interval_seconds <= 60:
            raise ValueError("controller interval must be 5-60 seconds")
        if set(settings.cpu_budgets) != {"container_cpu", "vm_cpu"} or any(
            type(value) is not int or value < 0 for value in settings.cpu_budgets.values()
        ):
            raise ValueError("both shared CPU budgets must be explicit nonnegative integers")
        if settings.vm_image_id and (
            not settings.ssh_public_key.startswith(("ssh-ed25519 ", "ssh-rsa "))
            or not settings.vm_subnet_id.startswith(f"/subscriptions/{settings.subscription_id}/")
            or "\n" in settings.ssh_public_key
        ):
            raise ValueError("Docker activation requires an explicit subnet and public SSH key")
        if settings.vm_image_id:
            image = re.fullmatch(
                r"/subscriptions/([^/]+)/resourceGroups/[^/]+/providers/Microsoft\.Compute/"
                r"galleries/[^/]+/images/[^/]+/versions/[0-9]+\.[0-9]+\.[0-9]+",
                settings.vm_image_id,
                re.IGNORECASE,
            )
            if not image or image[1].lower() != settings.subscription_id.lower():
                raise ValueError(
                    "Docker image must be an exact gallery version in the selected subscription"
                )
        if settings.vm_size not in {
            "Standard_D4ds_v4",
            "Standard_D4s_v5",
            "Standard_D4as_v5",
            "Standard_D4ads_v5",
        }:
            raise ValueError("Docker worker size must be a supported four-vCPU SKU")
        return settings


def policies(path: Path) -> tuple[dict[str, PoolPolicy], dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if set(data["pools"]) != {"control", "general", "docker"}:
        raise ValueError("all three worker pool policies are required")
    result = {
        name: PoolPolicy(
            name,
            item["warm_idle"],
            item["maximum"],
            item["cooldown_seconds"],
            startup_timeout_seconds=600,
        )
        for name, item in data["pools"].items()
    }
    labels: dict[str, set[str]] = {}
    for name, item in data["pools"].items():
        low = item.get("warm_idle_low", item["warm_idle"])
        if type(low) is not int or not 0 <= low <= item["warm_idle"]:
            raise ValueError("low-demand reserve must be between zero and the warm reserve")
        expected_cpu = 1 if name == "control" else 4
        expected_group = "vm_cpu" if name == "docker" else "container_cpu"
        if (
            type(item["cpu_per_runner"]) is not int
            or item["cpu_per_runner"] != expected_cpu
            or item["quota_group"] != expected_group
        ):
            raise ValueError("pool CPU accounting differs from its fixed worker shape")
        if (
            not isinstance(item["labels"], list)
            or not item["labels"]
            or not all(
                isinstance(label, str) and label.strip() == label and label
                for label in item["labels"]
            )
        ):
            raise ValueError("pool labels must be nonempty strings")
        labels[name] = {label.casefold() for label in item["labels"]}
    for name, own in labels.items():
        others = set().union(*(value for key, value in labels.items() if key != name))
        if not own - others:
            raise ValueError("every pool needs an exclusive routing label")
    return result, data

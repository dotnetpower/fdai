"""Private target and reviewed-control profiles for bounded Entra convergence."""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fdai_deployment_cli.contracts import canonical_digest, load_json_object
from fdai_deployment_cli.entra_control_profile import validate_control_profile

_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,127}")
_MAX_PROFILE_BYTES = 262_144


@dataclass(frozen=True, slots=True, repr=False)
class EntraTargetProfile:
    """Private exact target and approved executor identity."""

    environment: str
    target_binding: str
    executor_object_id: str = field(repr=False)
    executor_client_id: str = field(repr=False)
    executor_display_name: str = field(repr=False)
    executor_azure_config_dir: Path = field(repr=False)
    control_profile_digest: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> EntraTargetProfile:
        if (
            set(value)
            != {
                "schema_version",
                "environment",
                "target_binding",
                "executor_object_id",
                "executor_client_id",
                "executor_display_name",
                "executor_azure_config_dir",
                "control_profile_digest",
            }
            or value.get("schema_version") != "fdai.entra-target-profile.v2"
        ):
            raise ValueError("Entra target profile fields are invalid")
        environment = _text(value, "environment")
        target_binding = _text(value, "target_binding")
        executor_object_id = _text(value, "executor_object_id")
        executor_client_id = _text(value, "executor_client_id")
        executor_display_name = _text(value, "executor_display_name")
        executor_azure_config_dir = Path(_text(value, "executor_azure_config_dir"))
        control_profile_digest = _text(value, "control_profile_digest")
        if (
            environment not in {"dev", "staging", "prod"}
            or _DIGEST.fullmatch(target_binding) is None
            or _GUID.fullmatch(executor_object_id) is None
            or _GUID.fullmatch(executor_client_id) is None
            or _NAME.fullmatch(executor_display_name) is None
            or not executor_azure_config_dir.is_absolute()
            or ".." in executor_azure_config_dir.parts
            or _DIGEST.fullmatch(control_profile_digest) is None
        ):
            raise ValueError("Entra target profile values are invalid")
        return cls(
            environment=environment,
            target_binding=target_binding,
            executor_object_id=executor_object_id,
            executor_client_id=executor_client_id,
            executor_display_name=executor_display_name,
            executor_azure_config_dir=executor_azure_config_dir,
            control_profile_digest=control_profile_digest,
        )

    @property
    def digest(self) -> str:
        return canonical_digest(self.to_mapping())

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": "fdai.entra-target-profile.v2",
            "environment": self.environment,
            "target_binding": self.target_binding,
            "executor_object_id": self.executor_object_id,
            "executor_client_id": self.executor_client_id,
            "executor_display_name": self.executor_display_name,
            "executor_azure_config_dir": str(self.executor_azure_config_dir),
            "control_profile_digest": self.control_profile_digest,
        }


@dataclass(frozen=True, slots=True, repr=False)
class EntraControlProfile:
    value: dict[str, Any] = field(repr=False)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> EntraControlProfile:
        normalized = json.loads(json.dumps(value))
        if not isinstance(normalized, dict):
            raise ValueError("Entra control profile is invalid")
        validate_control_profile(normalized)
        return cls(normalized)

    @property
    def digest(self) -> str:
        return canonical_digest(self.value)

    @property
    def premium_service_plan(self) -> str:
        return str(self.value["premium_service_plan"])

    @property
    def role_groups(self) -> dict[str, str]:
        groups = self.value["role_groups"]
        assert isinstance(groups, dict)
        return {str(key): str(item) for key, item in groups.items()}

    @property
    def conditional_access_policies(self) -> list[dict[str, Any]]:
        return _dict_list(self.value["conditional_access_policies"])

    @property
    def access_reviews(self) -> list[dict[str, Any]]:
        return _dict_list(self.value["access_reviews"])

    @property
    def authentication_methods(self) -> list[dict[str, Any]]:
        return _dict_list(self.value["authentication_methods"])

    @property
    def azure_policy_assignments(self) -> list[dict[str, Any]]:
        return _dict_list(self.value["azure_policy_assignments"])


def load_target_profile(path: Path) -> EntraTargetProfile:
    descriptor = open_private_profile(path)
    try:
        return load_target_profile_descriptor(descriptor)
    finally:
        os.close(descriptor)


def load_control_profile(path: Path) -> EntraControlProfile:
    descriptor = open_private_profile(path)
    try:
        return load_control_profile_descriptor(descriptor)
    finally:
        os.close(descriptor)


def load_target_profile_descriptor(descriptor: int) -> EntraTargetProfile:
    return EntraTargetProfile.from_mapping(_read_private_object(descriptor, "Entra target profile"))


def load_control_profile_descriptor(descriptor: int) -> EntraControlProfile:
    return EntraControlProfile.from_mapping(
        _read_private_object(descriptor, "Entra control profile")
    )


def open_private_profile(path: Path) -> int:
    if not path.is_absolute():
        raise ValueError("Entra profile path MUST be absolute")
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        _validate_private_descriptor(descriptor)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _read_private_object(descriptor: int, label: str) -> dict[str, Any]:
    _validate_private_descriptor(descriptor)
    os.lseek(descriptor, 0, os.SEEK_SET)
    before = os.fstat(descriptor)
    payload = os.read(descriptor, _MAX_PROFILE_BYTES + 1)
    after = os.fstat(descriptor)
    if (
        not 0 < len(payload) <= _MAX_PROFILE_BYTES
        or len(payload) != before.st_size
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ctime_ns != after.st_ctime_ns
    ):
        raise ValueError(f"{label} changed or exceeded its bound")
    return load_json_object(payload, label=label, max_bytes=_MAX_PROFILE_BYTES)


def _validate_private_descriptor(descriptor: int) -> None:
    details = os.fstat(descriptor)
    if (
        not stat.S_ISREG(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o600
        or details.st_uid != os.geteuid()
        or details.st_nlink != 1
    ):
        raise PermissionError("Entra profile MUST be a current-UID mode-0600 single-link file")


def _dict_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("Entra control profile collection is invalid")
    return value


def _text(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise ValueError(f"Entra profile {key} is invalid")
    return item

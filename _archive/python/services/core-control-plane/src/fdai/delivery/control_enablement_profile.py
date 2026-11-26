"""Load bounded, deployment-owned control preferences without provider access."""

from pathlib import Path

from fdai_service_contracts.control_enablement_profile import ControlEnablementProfiles
from pydantic import ValidationError

_MAXIMUM_PROFILE_BYTES = 65_536


def load_control_enablement_profiles(path: Path | None) -> ControlEnablementProfiles | None:
    if path is None:
        return None
    try:
        with path.open("rb") as stream:
            material = stream.read(_MAXIMUM_PROFILE_BYTES + 1)
    except OSError:
        raise ValueError("deployment control enablement profile is unavailable") from None
    if len(material) > _MAXIMUM_PROFILE_BYTES:
        raise ValueError("control enablement profile exceeds the byte limit")
    try:
        return ControlEnablementProfiles.model_validate_json(material)
    except ValidationError:
        raise ValueError("deployment control enablement profile is invalid") from None

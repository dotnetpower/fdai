"""The customer-owned installation declaration: the only source of enrollment settings.

The Agent derives Entities and reported state from its cluster, but channel, version range,
region, allowed regions, maintenance windows and configuration are customer decisions. This
strict file carries them, so the Agent never invents a setting. Product binding, plan duration
and fencing generation are not declarable here; they follow separate approvals.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.lifecycle_configuration import validate_configuration_package_for_signing
from fdai_deployment_cli.private_output import read_private_bytes
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from fdai_lifecycle_agent.strict_json import load_json

DECLARATION_SCHEMA = "fdai.lifecycle-installation-declaration.v1"
MAX_DECLARATION_BYTES = 64 * 1024

_IDENTIFIER = r"^[a-z][a-z0-9-]{0,62}$"
# Built-in channels are upper case with underscores (DEV, RELEASE_CANDIDATE, RELEASE); custom
# channels and legacy fixtures are lower case with hyphens.
_CHANNEL = r"^[A-Za-z][A-Za-z0-9_-]{0,63}$"
_RANGE = r"^[\x21-\x7e]+(?: [\x21-\x7e]+)*$"
_WALL_CLOCK = r"^[0-2][0-9]:[0-5][0-9]:[0-5][0-9]$"
_DURATION = r"^P(?:[0-9]+D)?(?:T(?:[0-9]+H)?(?:[0-9]+M)?(?:[0-9]+S)?)?$"
_ZONE = r"^[A-Za-z][A-Za-z0-9_+/-]{0,63}$"

type Identifier = Annotated[str, StringConstraints(pattern=_IDENTIFIER)]
type Channel = Annotated[str, StringConstraints(pattern=_CHANNEL)]
type VersionRange = Annotated[str, StringConstraints(max_length=128, pattern=_RANGE)]
type WallClock = Annotated[str, StringConstraints(pattern=_WALL_CLOCK)]
type Duration = Annotated[str, StringConstraints(max_length=32, pattern=_DURATION)]
type Zone = Annotated[str, StringConstraints(pattern=_ZONE)]


class DeclaredWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    start: WallClock
    duration: Duration
    timezone: Zone
    allows_downtime: bool = False


class DeclaredSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    channel: Channel
    version_range: VersionRange
    region: Identifier
    allowed_regions: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=64)]
    windows: Annotated[tuple[DeclaredWindow, ...], Field(min_length=1, max_length=16)]


class DeclaredConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_: Annotated[dict[str, object], Field(alias="schema")]
    environment: dict[str, object]
    entity_overrides: Annotated[tuple[dict[str, object], ...], Field(max_length=256)]


class InstallationDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["fdai.lifecycle-installation-declaration.v1"] = Field(alias="schema")
    installation_id: Identifier
    settings: DeclaredSettings
    configuration: DeclaredConfiguration

    def enrollment_template(self) -> dict[str, object]:
        """The customer-owned part of the signed enrollment payload."""

        settings = self.settings.model_dump(mode="json")
        configuration = self.configuration.model_dump(mode="json", by_alias=True)
        return {
            "installation_id": self.installation_id,
            "settings": settings,
            "configuration": configuration,
        }


class DeclarationError(ValueError):
    """The declaration is unreadable or outside its schema; carries no file content."""


def load_declaration(path: Path) -> InstallationDeclaration:
    try:
        document = load_json(
            read_private_bytes(path, max_bytes=MAX_DECLARATION_BYTES),
            label="installation declaration",
        )
        # JSON-mode validation keeps strict types while accepting JSON arrays as tuples.
        declaration = InstallationDeclaration.model_validate_json(canonical_bytes(document))
        validate_configuration_package_for_signing(
            {
                "environment": declaration.configuration.environment,
                "entity_overrides": declaration.configuration.entity_overrides,
            }
        )
    except (OSError, ValueError, ValidationError) as error:
        raise DeclarationError("installation_declaration_invalid") from error
    return declaration

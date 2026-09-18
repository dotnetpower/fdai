"""Bind a generic Console build to public Entra and API deployment settings."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from urllib.parse import urlsplit

from fdai_deployment_cli.contracts import load_json_object
from fdai_deployment_cli.offline_kit import _read_regular
from fdai_deployment_cli.private_output import _open_private_parent

CONFIG_FILENAME = "fdai-config.js"
CONFIG_PLACEHOLDER = b"globalThis.__FDAI_CONSOLE_CONFIG__ = null;\n"
MANUAL_STUDIO_PLACEHOLDER_URL = "https://manual-studio.invalid/manuals"
_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_FIELDS = {
    "schema_version",
    "operator_api_base_url",
    "ingestion_api_base_url",
    "tenant_id",
    "spa_client_id",
    "api_scope",
}


def render_console_config(settings: bytes) -> bytes:
    """Validate public settings and render an external, authentication-only script.

    This contains no secret or authorization decision. The browser still obtains
    an Entra token and the APIs independently validate it. Unknown keys, including
    authentication bypass flags, are rejected.
    """
    values = load_json_object(settings, label="Console settings", max_bytes=16_384)
    if set(values) != _FIELDS or values["schema_version"] != "fdai.console-runtime.v1":
        raise ValueError("Console settings fields do not match fdai.console-runtime.v1")
    text_values: dict[str, str] = {}
    for key, value in values.items():
        if not isinstance(value, str) or not value.isascii():
            raise ValueError("Console settings MUST contain only ASCII string values")
        text_values[key] = value
    for field in ("tenant_id", "spa_client_id"):
        value = text_values[field]
        if re.fullmatch(_UUID, value) is None:
            raise ValueError(f"Console {field} MUST be a UUID")
    for field in ("operator_api_base_url", "ingestion_api_base_url"):
        value = text_values[field]
        parsed = urlsplit(value)
        if (
            not value.lower().startswith("https://")
            or any(
                character.isspace() or ord(character) < 32 or ord(character) == 127
                for character in value
            )
            or any(character in value for character in "\\?#")
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                f"Console {field} MUST be HTTPS without credentials, query, or fragment"
            )
        try:
            _ = parsed.port
        except ValueError as exc:
            raise ValueError(f"Console {field} has an invalid port") from exc
    scope = text_values["api_scope"]
    if re.fullmatch(rf"api://{_UUID}/[A-Za-z0-9._-]+", scope) is None:
        raise ValueError("Console api_scope MUST identify an Entra API application scope")
    document = json.dumps(text_values, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"globalThis.__FDAI_CONSOLE_CONFIG__ = {document};\n".encode("ascii")


def configure_console(
    directory: Path,
    settings: Path,
    *,
    manual_studio_url: str | None = None,
) -> dict[str, object]:
    """Replace only the shipped placeholder in a private prebuilt Console directory.

    Repeating identical settings is a no-op. A different existing configuration
    requires a fresh copy of the original build, preventing an implicit tenant
    switch. No package manager, build process, Azure call, or publication runs.
    """
    settings_parent = _open_private_parent(settings)
    os.close(settings_parent)
    details = settings.lstat()
    if stat.S_IMODE(details.st_mode) != 0o600 or details.st_uid != os.geteuid():
        raise PermissionError("Console settings MUST be a current-UID mode-0600 file")
    rendered = render_console_config(_read_regular(settings, 16_384))
    target = directory / CONFIG_FILENAME
    parent = _open_private_parent(target)
    temporary = ".fdai-config.js.pending"
    created = False
    try:
        current = _read_regular(target, 16_384)
        if current == rendered:
            changed = False
        elif current != CONFIG_PLACEHOLDER:
            raise ValueError(
                "Console config is not the shipped placeholder; use a fresh build copy"
            )
        else:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent,
            )
            created = True
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(rendered)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, CONFIG_FILENAME, src_dir_fd=parent, dst_dir_fd=parent)
            created = False
            os.fsync(parent)
            changed = True
    finally:
        if created:
            os.unlink(temporary, dir_fd=parent)
        os.close(parent)
    manual_pages_configured = _configure_manual_studio(directory, manual_studio_url)
    return {
        "schema_version": "fdai.console-configured.v1",
        "runtime_config_digest": hashlib.sha256(rendered).hexdigest(),
        "authentication": "entra",
        "changed": changed,
        "manual_studio_pages_configured": manual_pages_configured,
        "cloud_mutation_performed": False,
        "console_access_verified": False,
    }


def _configure_manual_studio(directory: Path, manual_studio_url: str | None) -> int:
    """Replace only the reserved Manual Studio origin in prebuilt share pages."""

    manual_root = directory / "manuals"
    if not manual_root.exists():
        return 0
    if manual_studio_url is None:
        raise ValueError("Console Manual Studio URL is required for bundled share pages")
    parsed = urlsplit(manual_studio_url)
    if (
        not manual_studio_url.startswith("https://")
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "\\" in manual_studio_url
        or any(
            character.isspace() or ord(character) < 32 or ord(character) > 126
            for character in manual_studio_url
        )
    ):
        raise ValueError("Console Manual Studio URL MUST be a safe HTTPS base URL")
    manual_studio_url = manual_studio_url.rstrip("/")
    if manual_studio_url == MANUAL_STUDIO_PLACEHOLDER_URL:
        raise ValueError("Console Manual Studio URL MUST replace the build placeholder")
    details = manual_root.lstat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or manual_root.is_symlink()
        or details.st_uid != os.geteuid()
    ):
        raise ValueError("Console Manual Studio directory is invalid")
    manual_root.chmod(0o700)
    html_files = sorted(manual_root.glob("*.html"))
    if not html_files:
        raise ValueError("Console Manual Studio has no share pages")
    placeholder = MANUAL_STUDIO_PLACEHOLDER_URL.encode("ascii")
    replacement = manual_studio_url.encode("ascii")
    parent = _open_private_parent(manual_root / "catalog.json")
    pending: list[str] = []
    try:
        for path in html_files:
            current = _read_regular(path, 4 * 1024 * 1024)
            if placeholder in current:
                configured = current.replace(placeholder, replacement)
            elif replacement in current:
                continue
            else:
                raise ValueError("Console Manual Studio share page is not configurable")
            temporary = f".{path.name}.pending"
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent,
            )
            pending.append(temporary)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(configured)
                stream.flush()
                os.fsync(stream.fileno())
        for path in html_files:
            temporary = f".{path.name}.pending"
            if temporary in pending:
                os.replace(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent)
                pending.remove(temporary)
        os.fsync(parent)
    finally:
        for temporary in pending:
            os.unlink(temporary, dir_fd=parent)
        os.close(parent)
    return len(html_files)

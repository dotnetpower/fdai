"""Native SharePoint connector deployment ownership checks."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = REPO_ROOT / "infra" / "services" / "document-ingestion-api"


def test_native_connector_is_wired_to_the_deployed_service_module() -> None:
    root = (SERVICE_ROOT / "main.tf").read_text(encoding="utf-8")
    module = (SERVICE_ROOT / "modules" / "document-ingestion-api" / "main.tf").read_text(
        encoding="utf-8"
    )

    assert "sharepoint_connector = var.sharepoint_connector" in root
    for name in (
        "FDAI_SHAREPOINT_CONNECTOR_ENABLED",
        "FDAI_SHAREPOINT_TARGET_TENANT_ID",
        "FDAI_SHAREPOINT_CLIENT_ID",
        "FDAI_SHAREPOINT_SITE_ID",
        "FDAI_SHAREPOINT_DRIVE_ID",
    ):
        assert name in module


def test_power_platform_is_not_a_native_connector_dependency() -> None:
    paths = (
        REPO_ROOT / "services" / "document-ingestion-api" / "src",
        SERVICE_ROOT,
        REPO_ROOT / "config",
    )
    offenders = []
    for directory in paths:
        for path in directory.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".tf", ".yaml", ".yml"}:
                continue
            text = path.read_text(encoding="utf-8").casefold()
            if "power_platform" in text or "power platform" in text:
                offenders.append(path.relative_to(REPO_ROOT).as_posix())
    assert offenders == []

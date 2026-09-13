"""Exact managed/gallery image requirements cannot be inferred from a friendly SKU name."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/deployment/azure"))

from genesis_checks import CheckError  # noqa: E402
from genesis_vm_image_requirements import image_requirements  # noqa: E402

SUB = "00000000-0000-0000-0000-000000000001"
BASE = f"/subscriptions/{SUB}/resourceGroups/example/providers/Microsoft.Compute"
IMAGE = BASE + "/images/example"
GALLERY = BASE + "/galleries/example/images/example/versions/1.0.0"


def managed():
    return {
        "id": IMAGE,
        "location": "East US",
        "provisioningState": "Succeeded",
        "diskSizeGB": 64,
        "hyperVGeneration": "V2",
        "osType": "Linux",
        "osState": "Generalized",
    }


def verify(image, responses):
    pages = iter(responses)
    calls = []

    def read(command, **kwargs):
        assert command[:4] == ["/usr/bin/az", "rest", "--method", "get"]
        assert kwargs["timeout"] == 30
        calls.append(command[command.index("--url") + 1])
        return json.dumps(next(pages))

    result = image_requirements(
        image=image,
        subscription_id=SUB,
        region="eastus",
        capture=read,
        cwd=ROOT,
        environment={},
    )
    return result, calls


def test_managed_image_identity_guest_and_actual_disk_are_required():
    result, calls = verify(IMAGE, [managed()])
    assert result == {"diskSizeGB": 64, "hyperVGeneration": "V2", "osType": "Linux"}
    assert len(calls) == 1
    assert "id" not in result


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", IMAGE + "-other"),
        ("location", "westus"),
        ("provisioningState", "Creating"),
        ("diskSizeGB", None),
        ("diskSizeGB", True),
        ("diskSizeGB", "64"),
        ("diskSizeGB", 0),
        ("hyperVGeneration", "V1"),
        ("osType", "Windows"),
        ("osState", "Specialized"),
    ],
)
def test_incomplete_or_different_managed_image_is_not_accepted(field, value):
    response = managed()
    response[field] = value
    with pytest.raises(CheckError, match="evidence_incomplete"):
        verify(IMAGE, [response])


def gallery():
    definition = {
        "id": GALLERY.rsplit("/", 2)[0],
        "provisioningState": "Succeeded",
        "hyperVGeneration": "V2",
        "architecture": "x64",
        "osType": "Linux",
        "osState": "Generalized",
    }
    version = {
        "id": GALLERY,
        "provisioningState": "Succeeded",
        "diskSizeGB": 128,
        "replicas": [{"region": "East US", "state": "Completed"}],
    }
    return definition, version


def test_numeric_gallery_version_requires_definition_and_regional_replica():
    result, calls = verify(GALLERY, gallery())
    assert result["diskSizeGB"] == 128
    assert len(calls) == 2 and calls[-1].endswith("&$expand=ReplicationStatus")


@pytest.mark.parametrize(
    "fault",
    ["arm", "missing_disk", "wrong_version", "no_replica", "replicating", "duplicate_replica"],
)
def test_gallery_missing_requirements_remain_blocked(fault):
    definition, version = gallery()
    if fault == "arm":
        definition["architecture"] = "Arm64"
    elif fault == "missing_disk":
        version.pop("diskSizeGB")
    elif fault == "wrong_version":
        version["id"] = GALLERY[:-5] + "2.0.0"
    elif fault == "no_replica":
        version["replicas"] = []
    elif fault == "replicating":
        version["replicas"][0]["state"] = "Replicating"
    else:
        version["replicas"] *= 2
    with pytest.raises(CheckError, match="evidence_incomplete"):
        verify(GALLERY, [definition, version])


@pytest.mark.parametrize(
    "image",
    [
        GALLERY.replace("1.0.0", "latest"),
        GALLERY.rsplit("/", 2)[0],
        IMAGE + "?secret=example",
        IMAGE.replace(SUB, "00000000-0000-0000-0000-000000000002"),
    ],
)
def test_unversioned_foreign_or_injected_resource_has_no_read(image):
    with pytest.raises(CheckError, match="evidence_incomplete"):
        verify(image, [])

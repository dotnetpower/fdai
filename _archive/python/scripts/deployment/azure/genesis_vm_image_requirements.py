"""Read exact image hardware requirements without equating compatibility with image trust."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from pathlib import Path

from genesis_checks import CheckError
from genesis_runner_image_skus import EVIDENCE_INVALID, load_sku_json

_UUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
_SEGMENT = r"[A-Za-z0-9._()-]+"
_IMAGE = re.compile(
    rf"/subscriptions/(?P<subscription>{_UUID})/resourceGroups/{_SEGMENT}/"
    rf"providers/Microsoft\.Compute/(?:images/{_SEGMENT}|"
    rf"galleries/{_SEGMENT}/images/{_SEGMENT}/versions/[0-9]+\.[0-9]+\.[0-9]+)",
    re.IGNORECASE,
)


def image_requirements(
    *,
    image: str,
    subscription_id: str,
    region: str,
    capture: Callable[..., str],
    cwd: Path,
    environment: Mapping[str, str],
) -> dict[str, object]:
    """Read disk size for one managed image or exact gallery version in the selected target.

    Managed image provenance and guest architecture remain the existing image verifier's job.
    Gallery versions need their definition and completed target-region replica. Missing fields,
    foreign identities, specialized images or incompatible guest models remain blocked.
    """
    match = _IMAGE.fullmatch(image)
    if match is None or match["subscription"].casefold() != subscription_id.casefold():
        raise CheckError(EVIDENCE_INVALID, 3)

    def read(resource: str, query: str, *, replication: bool = False) -> dict[str, object]:
        url = f"https://management.azure.com{resource}?api-version=2024-03-01"
        if replication:
            url += "&$expand=ReplicationStatus"
        raw = capture(
            [
                "/usr/bin/az",
                "rest",
                "--method",
                "get",
                "--url",
                url,
                "--query",
                query,
                "--output",
                "json",
                "--only-show-errors",
            ],
            cwd=cwd,
            env=environment,
            timeout=30,
            reason=EVIDENCE_INVALID,
        )
        value = load_sku_json(raw.encode("utf-8"), max_bytes=65_536)
        if (
            not isinstance(value.get("id"), str)
            or str(value["id"]).casefold() != resource.casefold()
            or value.get("provisioningState") != "Succeeded"
        ):
            raise CheckError(EVIDENCE_INVALID, 3)
        return value

    if "/galleries/" not in image.casefold():
        value = read(
            image,
            "{id:id,location:location,provisioningState:properties.provisioningState,"
            "diskSizeGB:properties.storageProfile.osDisk.diskSizeGB,"
            "hyperVGeneration:properties.hyperVGeneration,"
            "osType:properties.storageProfile.osDisk.osType,"
            "osState:properties.storageProfile.osDisk.osState}",
        )
        if _location(value.get("location")) != _location(region):
            raise CheckError(EVIDENCE_INVALID, 3)
        disk = value.get("diskSizeGB")
    else:
        definition_id = image.rsplit("/", 2)[0]
        value = read(
            definition_id,
            "{id:id,provisioningState:properties.provisioningState,"
            "hyperVGeneration:properties.hyperVGeneration,architecture:properties.architecture,"
            "osType:properties.osType,osState:properties.osState}",
        )
        if value.get("architecture") != "x64":
            raise CheckError(EVIDENCE_INVALID, 3)
        version = read(
            image,
            "{id:id,provisioningState:properties.provisioningState,"
            "diskSizeGB:properties.storageProfile.osDiskImage.sizeInGB,"
            "replicas:properties.replicationStatus.summary[].{region:region,state:state}}",
            replication=True,
        )
        replicas = version.get("replicas")
        if not isinstance(replicas, list) or not 1 <= len(replicas) <= 128:
            raise CheckError(EVIDENCE_INVALID, 3)
        matches = []
        for item in replicas:
            if not isinstance(item, dict):
                raise CheckError(EVIDENCE_INVALID, 3)
            if _location(item.get("region")) == _location(region):
                matches.append(item)
        if len(matches) != 1 or matches[0].get("state") != "Completed":
            raise CheckError(EVIDENCE_INVALID, 3)
        disk = version.get("diskSizeGB")
    if (
        type(disk) is not int
        or not 1 <= disk <= 2048
        or value.get("hyperVGeneration") != "V2"
        or value.get("osType") != "Linux"
        or value.get("osState") != "Generalized"
    ):
        raise CheckError(EVIDENCE_INVALID, 3)
    return {"diskSizeGB": disk, "hyperVGeneration": "V2", "osType": "Linux"}


def _location(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z][A-Za-z0-9 ]{0,63}", value) is None:
        raise CheckError(EVIDENCE_INVALID, 3)
    return value.replace(" ", "").casefold()

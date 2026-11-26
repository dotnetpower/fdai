"""Load only reviewed, digest-pinned PNG assets shipped with the service-contract package."""

from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass
from importlib import resources

from .wara_guidance import ReferenceImage

_MAXIMUM_ASSET_BYTES = 2_097_152
_MAXIMUM_DIMENSION = 4_096
_MAXIMUM_PIXELS = 16_777_216
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class PackagedReferenceImage:
    content: bytes
    width: int
    height: int


def verify_reference_image_bytes(image: ReferenceImage, content: bytes) -> PackagedReferenceImage:
    """Verify bounded static PNG bytes against the typed content-addressed asset reference."""

    if len(content) > _MAXIMUM_ASSET_BYTES:
        raise ValueError("WARA reference image exceeds its byte limit")
    if "sha256:" + hashlib.sha256(content).hexdigest() != image.digest:
        raise ValueError("WARA reference image digest does not match its contract")
    if len(content) < len(_PNG_SIGNATURE) or content[:8] != _PNG_SIGNATURE:
        raise ValueError("WARA reference image is not a PNG")

    offset = len(_PNG_SIGNATURE)
    width = height = 0
    seen_header = seen_data = seen_end = False
    chunks = 0
    while offset < len(content):
        if offset + 12 > len(content):
            raise ValueError("WARA reference image has a truncated PNG chunk")
        length = struct.unpack_from(">I", content, offset)[0]
        chunk_type = content[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(content):
            raise ValueError("WARA reference image has a truncated PNG chunk")
        chunk_data = content[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack_from(">I", content, offset + 8 + length)[0]
        if zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF != expected_crc:
            raise ValueError("WARA reference image contains an invalid PNG checksum")
        chunks += 1
        if chunks > 4_096:
            raise ValueError("WARA reference image contains too many PNG chunks")
        if not seen_header:
            if chunk_type != b"IHDR" or length != 13:
                raise ValueError("WARA reference image has an invalid PNG header")
            width, height = struct.unpack_from(">II", chunk_data)
            if (
                width < 1
                or height < 1
                or width > _MAXIMUM_DIMENSION
                or height > _MAXIMUM_DIMENSION
                or width * height > _MAXIMUM_PIXELS
            ):
                raise ValueError("WARA reference image dimensions exceed their limits")
            seen_header = True
        elif chunk_type == b"IHDR":
            raise ValueError("WARA reference image contains a duplicate PNG header")
        if chunk_type in {b"acTL", b"fcTL", b"fdAT"}:
            raise ValueError("WARA reference image must not be animated")
        if chunk_type == b"IDAT":
            seen_data = True
        if chunk_type == b"IEND":
            if length != 0 or end != len(content):
                raise ValueError("WARA reference image has an invalid PNG terminator")
            seen_end = True
            break
        offset = end

    if not seen_header or not seen_data or not seen_end:
        raise ValueError("WARA reference image is an incomplete PNG")
    return PackagedReferenceImage(content=content, width=width, height=height)


def load_packaged_reference_image(image: ReferenceImage) -> PackagedReferenceImage:
    """Read an asset by its content-addressed filename; caller paths and URLs are never opened."""

    directory = resources.files("fdai_service_contracts").joinpath("data", "wara-guidance-assets")
    try:
        with directory.joinpath(f"{image.asset_id}.png").open("rb") as stream:
            content = stream.read(_MAXIMUM_ASSET_BYTES + 1)
    except OSError as exc:
        raise ValueError("packaged WARA reference image is unavailable") from exc
    return verify_reference_image_bytes(image, content)


__all__ = [
    "PackagedReferenceImage",
    "load_packaged_reference_image",
    "verify_reference_image_bytes",
]

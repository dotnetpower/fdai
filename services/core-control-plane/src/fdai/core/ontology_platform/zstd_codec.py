"""Deterministic Zstandard (PEP 784 stdlib compression.zstd) codec for ontology and archives."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fdai.core.ontology_platform.archive_manifest import (
    ArchiveManifest,
    ArchiveSourcePartition,
    ArchiveVerificationReceipt,
    build_archive_manifest,
    verify_archive_manifest,
)
from fdai.rule_catalog.schema._zstd_compat import zstd_runtime as zstd

ZSTD_PROFILE_FRAME = "zstd-v1"
ZSTD_PROFILE_DICT = "zstd-dict-v1"
_DEFAULT_MAX_BYTES = 16 * 1024 * 1024


def _sha256_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def canonical_json_bytes(value: Any, *, max_bytes: int = _DEFAULT_MAX_BYTES) -> bytes:
    """Encode a JSON-compatible value into deterministic UTF-8 canonical JSON bytes."""

    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > max_bytes:
        raise ValueError(f"canonical JSON payload exceeds {max_bytes} bytes")
    return encoded


@dataclass(frozen=True, slots=True)
class ZstdDictionaryArtifact:
    """Content-addressed trained Zstandard dictionary for repetitive operational records."""

    dict_bytes: bytes
    dict_digest: str
    dict_id: int
    sample_count: int

    def __post_init__(self) -> None:
        if not self.dict_bytes:
            raise ValueError("ZstdDictionaryArtifact.dict_bytes MUST be non-empty")
        if self.dict_digest != _sha256_bytes(self.dict_bytes):
            raise ValueError("ZstdDictionaryArtifact.dict_digest does not match dict_bytes")
        if self.sample_count < 1:
            raise ValueError("ZstdDictionaryArtifact.sample_count MUST be positive")


@dataclass(frozen=True, slots=True)
class ZstdCompressedArtifact:
    """Immutable Zstandard-compressed payload with dual uncompressed/compressed SHA-256 pins."""

    profile: str
    compressed_bytes: bytes
    raw_byte_length: int
    compressed_byte_length: int
    uncompressed_digest: str
    compressed_digest: str
    dictionary_digest: str | None = None

    def __post_init__(self) -> None:
        if self.profile not in {ZSTD_PROFILE_FRAME, ZSTD_PROFILE_DICT}:
            raise ValueError(f"unsupported zstd profile {self.profile!r}")
        if not self.compressed_bytes:
            raise ValueError("compressed_bytes MUST be non-empty")
        if self.raw_byte_length < 1 or self.compressed_byte_length != len(self.compressed_bytes):
            raise ValueError("compressed artifact byte lengths are inconsistent")
        if self.compressed_digest != _sha256_bytes(self.compressed_bytes):
            raise ValueError("compressed_digest does not match compressed_bytes")
        if (self.profile == ZSTD_PROFILE_DICT) != (self.dictionary_digest is not None):
            raise ValueError("zstd-dict-v1 profile requires dictionary_digest and vice versa")

    @property
    def compression_ratio(self) -> float:
        """Return uncompressed-to-compressed ratio (e.g. 12.5 means 12.5x smaller)."""

        return round(self.raw_byte_length / max(self.compressed_byte_length, 1), 4)

    @property
    def space_savings_ratio(self) -> float:
        """Return fraction of bytes saved in [0.0, 1.0]."""

        return round(max(0.0, 1.0 - (self.compressed_byte_length / self.raw_byte_length)), 4)

    @property
    def space_savings_pct(self) -> float:
        """Return percentage of bytes saved (e.g. 92.4%)."""

        return round(self.space_savings_ratio * 100.0, 2)


@dataclass(frozen=True, slots=True)
class ZstdArchiveBundle:
    """Verified operational-history archive manifest bound to a Zstd-compressed payload."""

    manifest: ArchiveManifest
    artifact: ZstdCompressedArtifact
    verification_receipt: ArchiveVerificationReceipt


def train_zstd_dictionary(
    samples: Sequence[bytes | str | Mapping[str, Any]],
    *,
    dict_size: int = 4096,
) -> ZstdDictionaryArtifact:
    """Train a deterministic Zstandard dictionary from representative ontology/cohort records."""

    if len(samples) < 8:
        raise ValueError("train_zstd_dictionary requires at least 8 samples")
    if not 256 <= dict_size <= 131_072:
        raise ValueError("dict_size MUST be between 256 and 131072 bytes")
    encoded_samples: list[bytes] = []
    for sample in samples:
        if isinstance(sample, bytes):
            encoded_samples.append(sample)
        elif isinstance(sample, str):
            encoded_samples.append(sample.encode("utf-8"))
        else:
            encoded_samples.append(canonical_json_bytes(sample))
    trained = zstd.train_dict(encoded_samples, dict_size)
    raw_dict = bytes(trained.dict_content)
    return ZstdDictionaryArtifact(
        dict_bytes=raw_dict,
        dict_digest=_sha256_bytes(raw_dict),
        dict_id=int(trained.dict_id),
        sample_count=len(encoded_samples),
    )


def compress_canonical_json(
    payload: Any,
    *,
    level: int = 3,
    dictionary: ZstdDictionaryArtifact | None = None,
    max_raw_bytes: int = _DEFAULT_MAX_BYTES,
) -> ZstdCompressedArtifact:
    """Serialize `payload` to canonical JSON and compress with stdlib Zstandard."""

    if not -7 <= level <= 22:
        raise ValueError("zstd compression level MUST be between -7 and 22")
    raw = canonical_json_bytes(payload, max_bytes=max_raw_bytes)
    zdict = zstd.ZstdDict(dictionary.dict_bytes) if dictionary is not None else None
    compressed = bytes(zstd.compress(raw, level=level, zstd_dict=zdict))
    return ZstdCompressedArtifact(
        profile=ZSTD_PROFILE_DICT if dictionary is not None else ZSTD_PROFILE_FRAME,
        compressed_bytes=compressed,
        raw_byte_length=len(raw),
        compressed_byte_length=len(compressed),
        uncompressed_digest=_sha256_bytes(raw),
        compressed_digest=_sha256_bytes(compressed),
        dictionary_digest=dictionary.dict_digest if dictionary is not None else None,
    )


def decompress_canonical_json(
    artifact: ZstdCompressedArtifact,
    *,
    dictionary: ZstdDictionaryArtifact | None = None,
    max_decompressed_bytes: int = _DEFAULT_MAX_BYTES,
) -> Any:
    """Verify digests, guard against decompression bombs, and decode canonical JSON."""

    if _sha256_bytes(artifact.compressed_bytes) != artifact.compressed_digest:
        raise ValueError("zstd compressed_digest verification failed")
    if artifact.dictionary_digest is not None:
        if dictionary is None or dictionary.dict_digest != artifact.dictionary_digest:
            raise ValueError("zstd dictionary_digest mismatch or missing dictionary")
    elif dictionary is not None:
        raise ValueError("unexpected zstd dictionary supplied for frame-only artifact")
    if artifact.raw_byte_length > max_decompressed_bytes:
        raise ValueError("declared raw_byte_length exceeds max_decompressed_bytes")
    zdict = zstd.ZstdDict(dictionary.dict_bytes) if dictionary is not None else None
    decompressor = zstd.ZstdDecompressor(zstd_dict=zdict)
    raw = decompressor.decompress(
        artifact.compressed_bytes,
        max_length=max_decompressed_bytes + 1,
    )
    raw_bytes = bytes(raw)
    if len(raw_bytes) > max_decompressed_bytes or len(raw_bytes) != artifact.raw_byte_length:
        raise ValueError("decompressed zstd payload length does not match declared bound")
    if _sha256_bytes(raw_bytes) != artifact.uncompressed_digest:
        raise ValueError("zstd uncompressed_digest verification failed")
    return json.loads(raw_bytes.decode("utf-8"))


def build_zstd_archive_bundle(
    partitions: tuple[ArchiveSourcePartition, ...],
    payload: Any,
    *,
    created_at: datetime,
    dictionary: ZstdDictionaryArtifact | None = None,
    level: int = 3,
    encryption_profile: str = "aes-256-gcm",
    destination_class: str = "cold-object-store",
    retention_class: str = "regulatory-365d",
) -> ZstdArchiveBundle:
    """Compress an archive payload with Zstd and bind it to a verified `ArchiveManifest`."""

    artifact = compress_canonical_json(payload, level=level, dictionary=dictionary)
    receipt_seed = _sha256_bytes(
        f"{artifact.uncompressed_digest}:{artifact.compressed_digest}".encode()
    )
    manifest = build_archive_manifest(
        partitions,
        archive_content_digest=artifact.compressed_digest,
        compression_profile=artifact.profile,
        encryption_profile=encryption_profile,
        destination_class=destination_class,
        retention_class=retention_class,
        creation_receipt_digest=receipt_seed,
        created_at=created_at,
    )
    verification = verify_archive_manifest(
        manifest,
        observed_archive_content_digest=artifact.compressed_digest,
        observed_source_partition_digests=tuple(p.content_digest for p in partitions),
        observed_source_schema_versions=tuple({p.schema_version for p in partitions}),
        observed_ontology_release_digests=tuple({p.ontology_release_digest for p in partitions}),
        verified_at=created_at,
    )
    return ZstdArchiveBundle(
        manifest=manifest,
        artifact=artifact,
        verification_receipt=verification,
    )


__all__ = [
    "ZSTD_PROFILE_DICT",
    "ZSTD_PROFILE_FRAME",
    "ZstdArchiveBundle",
    "ZstdCompressedArtifact",
    "ZstdDictionaryArtifact",
    "build_zstd_archive_bundle",
    "canonical_json_bytes",
    "compress_canonical_json",
    "decompress_canonical_json",
    "train_zstd_dictionary",
]

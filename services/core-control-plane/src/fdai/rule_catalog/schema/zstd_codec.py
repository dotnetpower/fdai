"""Bounded Zstandard (PEP 784 ``compression.zstd``) codec and dictionary compression.

Provides deterministic, fail-closed compression and decompression helpers for
FDAI catalog bundles, question-bank artifacts, snapshot mirrors, and shared
property payloads using Python 3.14's standard-library ``compression.zstd``
module (zero external dependencies).

Safety invariants:
- Canonical digests (``sha256:...``) are ALWAYS computed over the canonical
  uncompressed UTF-8 or raw bytes, never over the compressed stream, so
  provenance and audit hashes remain independent of compression levels.
- Every decompression path enforces a strict ``max_output_size`` ceiling via
  streaming ``ZstdDecompressor`` chunks so decompression bombs fail closed
  before allocating unbounded memory.
- Small-record dictionary training (``train_record_dictionary``) deterministically
  orders training samples and pins the resulting dictionary SHA-256 and ID.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from compression import zstd  # type: ignore[import-not-found]

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
DEFAULT_ZSTD_LEVEL = 3
ARCHIVE_ZSTD_LEVEL = 19
DEFAULT_MAX_OUTPUT_BYTES = 32 * 1024 * 1024
DEFAULT_DICT_SIZE = 32 * 1024
_STREAM_READ_CHUNK_BYTES = 64 * 1024
_MIN_LEVEL = -131072
_MAX_LEVEL = 22
_MIN_DICT_SIZE = 256
_MAX_DICT_SIZE = 1024 * 1024


class ZstdCodecError(ValueError):
    """Raised when Zstandard compression, decompression, or digest verification fails."""


@dataclass(frozen=True, slots=True)
class ZstdEnvelope:
    """Metadata and compressed bytes for one canonical payload."""

    uncompressed_sha256: str
    uncompressed_size: int
    compressed_size: int
    level: int
    dict_id: int
    compressed_bytes: bytes

    @property
    def compression_ratio(self) -> float:
        if self.compressed_size <= 0:
            return 1.0
        return self.uncompressed_size / self.compressed_size

    @property
    def space_savings_ratio(self) -> float:
        if self.uncompressed_size <= 0:
            return 0.0
        return max(0.0, 1.0 - (self.compressed_size / self.uncompressed_size))


@dataclass(frozen=True, slots=True)
class ZstdRecordDictionary:
    """Immutable trained Zstandard dictionary for small structured records."""

    dict_bytes: bytes
    dict_id: int
    dict_sha256: str
    sample_count: int
    total_sample_bytes: int

    def as_zstd_dict(self) -> zstd.ZstdDict:
        return zstd.ZstdDict(self.dict_bytes)


@dataclass(frozen=True, slots=True)
class ZstdDictionaryBatch:
    """Batch of records compressed with one shared Zstandard dictionary."""

    dict_sha256: str
    dict_id: int
    dict_bytes: bytes
    record_digests: tuple[str, ...]
    compressed_records: tuple[bytes, ...]
    uncompressed_total_bytes: int
    compressed_total_bytes: int

    @property
    def compression_ratio(self) -> float:
        if self.compressed_total_bytes <= 0:
            return 1.0
        return self.uncompressed_total_bytes / self.compressed_total_bytes


def canonical_sha256(data: bytes | str) -> str:
    """Return ``sha256:<hex>`` over canonical uncompressed bytes."""
    raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def is_zstd_frame(data: bytes) -> bool:
    """Return whether ``data`` starts with the RFC 8878 Zstandard frame magic."""
    return isinstance(data, (bytes, bytearray)) and len(data) >= 4 and bytes(data[:4]) == ZSTD_MAGIC


def compress_bytes(
    data: bytes,
    *,
    level: int = DEFAULT_ZSTD_LEVEL,
    dictionary: ZstdRecordDictionary | zstd.ZstdDict | None = None,
) -> ZstdEnvelope:
    """Compress ``data`` with ``compression.zstd`` and record its uncompressed SHA-256."""
    if not isinstance(data, (bytes, bytearray)):
        raise ZstdCodecError("data MUST be bytes")
    if (
        isinstance(level, bool)
        or not isinstance(level, int)
        or not (_MIN_LEVEL <= level <= _MAX_LEVEL)
    ):
        raise ZstdCodecError(
            f"zstd compression level MUST be an integer in [{_MIN_LEVEL}, {_MAX_LEVEL}]"
        )
    raw = bytes(data)
    zdict = _resolve_zstd_dict(dictionary)
    try:
        compressed = zstd.compress(raw, level=level, zstd_dict=zdict)
    except zstd.ZstdError as exc:
        raise ZstdCodecError(f"zstd compression failed: {exc}") from exc
    return ZstdEnvelope(
        uncompressed_sha256=canonical_sha256(raw),
        uncompressed_size=len(raw),
        compressed_size=len(compressed),
        level=level,
        dict_id=int(zdict.dict_id) if zdict is not None else 0,
        compressed_bytes=compressed,
    )


def decompress_bytes(
    data: bytes,
    *,
    max_output_size: int = DEFAULT_MAX_OUTPUT_BYTES,
    expected_uncompressed_sha256: str | None = None,
    dictionary: ZstdRecordDictionary | zstd.ZstdDict | None = None,
) -> bytes:
    """Decompress one Zstandard frame with strict output-size and SHA-256 bounds."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ZstdCodecError("compressed data MUST be non-empty bytes")
    if (
        isinstance(max_output_size, bool)
        or not isinstance(max_output_size, int)
        or max_output_size < 1
    ):
        raise ZstdCodecError("max_output_size MUST be a positive integer")
    raw_input = bytes(data)
    if not is_zstd_frame(raw_input):
        raise ZstdCodecError("payload does not start with the Zstandard magic header")

    zdict = _resolve_zstd_dict(dictionary)
    try:
        decompressor = zstd.ZstdDecompressor(zstd_dict=zdict)
        chunks: list[bytes] = []
        total = 0
        remaining_input: bytes = raw_input
        while True:
            budget = (max_output_size - total) + 1
            chunk_limit = min(budget, max(_STREAM_READ_CHUNK_BYTES, budget))
            chunk = decompressor.decompress(remaining_input, max_length=chunk_limit)
            if chunk:
                total += len(chunk)
                if total > max_output_size:
                    raise ZstdCodecError(
                        f"decompressed payload exceeds max_output_size ({max_output_size} bytes)"
                    )
                chunks.append(chunk)
            if decompressor.eof:
                if decompressor.unused_data:
                    raise ZstdCodecError("trailing bytes found after Zstandard frame EOF")
                break
            if decompressor.needs_input:
                raise ZstdCodecError("truncated Zstandard frame: unexpected end of input")
            remaining_input = b""
    except zstd.ZstdError as exc:
        raise ZstdCodecError(f"zstd decompression failed: {exc}") from exc

    output = b"".join(chunks)
    if expected_uncompressed_sha256 is not None:
        actual = canonical_sha256(output)
        normalized_expected = (
            expected_uncompressed_sha256
            if expected_uncompressed_sha256.startswith("sha256:")
            else f"sha256:{expected_uncompressed_sha256}"
        )
        if actual != normalized_expected:
            raise ZstdCodecError(
                f"uncompressed SHA-256 mismatch: expected {normalized_expected}, got {actual}"
            )
    return output


def compress_json(
    payload: object,
    *,
    level: int = DEFAULT_ZSTD_LEVEL,
    sort_keys: bool = True,
    dictionary: ZstdRecordDictionary | zstd.ZstdDict | None = None,
) -> ZstdEnvelope:
    """Serialize ``payload`` as canonical UTF-8 JSON and compress with Zstandard."""
    try:
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=sort_keys,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ZstdCodecError(f"payload is not valid finite JSON: {exc}") from exc
    return compress_bytes(serialized, level=level, dictionary=dictionary)


def decompress_json(
    data: bytes,
    *,
    max_output_size: int = DEFAULT_MAX_OUTPUT_BYTES,
    expected_uncompressed_sha256: str | None = None,
    dictionary: ZstdRecordDictionary | zstd.ZstdDict | None = None,
) -> Any:
    """Decompress a Zstandard JSON payload within ``max_output_size`` and parse it."""
    raw = decompress_bytes(
        data,
        max_output_size=max_output_size,
        expected_uncompressed_sha256=expected_uncompressed_sha256,
        dictionary=dictionary,
    )
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ZstdCodecError(f"decompressed payload is not valid UTF-8 JSON: {exc}") from exc


def train_record_dictionary(
    samples: Sequence[bytes | str],
    *,
    dict_size: int = DEFAULT_DICT_SIZE,
) -> ZstdRecordDictionary:
    """Train a deterministic Zstandard dictionary from representative small records."""
    if (
        isinstance(dict_size, bool)
        or not isinstance(dict_size, int)
        or not (_MIN_DICT_SIZE <= dict_size <= _MAX_DICT_SIZE)
    ):
        raise ZstdCodecError(
            f"dict_size MUST be an integer in [{_MIN_DICT_SIZE}, {_MAX_DICT_SIZE}]"
        )
    encoded_samples = tuple(
        sample.encode("utf-8") if isinstance(sample, str) else bytes(sample)
        for sample in samples
        if sample
    )
    if len(encoded_samples) < 8:
        raise ZstdCodecError("dictionary training requires at least 8 non-empty samples")
    total_bytes = sum(len(item) for item in encoded_samples)
    if total_bytes < dict_size:
        raise ZstdCodecError(
            f"total sample bytes ({total_bytes}) MUST be at least dict_size ({dict_size})"
        )
    try:
        trained = zstd.train_dict(encoded_samples, dict_size=dict_size)
    except zstd.ZstdError as exc:
        raise ZstdCodecError(f"zstd dictionary training failed: {exc}") from exc
    dict_bytes = bytes(trained.dict_content)
    return ZstdRecordDictionary(
        dict_bytes=dict_bytes,
        dict_id=int(trained.dict_id),
        dict_sha256=canonical_sha256(dict_bytes),
        sample_count=len(encoded_samples),
        total_sample_bytes=total_bytes,
    )


def compress_record_batch(
    records: Sequence[bytes | str],
    *,
    dictionary: ZstdRecordDictionary,
    level: int = DEFAULT_ZSTD_LEVEL,
) -> ZstdDictionaryBatch:
    """Compress a sequence of small records using a shared ``ZstdRecordDictionary``."""
    if not records:
        raise ZstdCodecError("records MUST be non-empty")
    zdict = dictionary.as_zstd_dict()
    digests: list[str] = []
    compressed_list: list[bytes] = []
    raw_total = 0
    comp_total = 0
    for record in records:
        raw = record.encode("utf-8") if isinstance(record, str) else bytes(record)
        digests.append(canonical_sha256(raw))
        comp = zstd.compress(raw, level=level, zstd_dict=zdict)
        compressed_list.append(comp)
        raw_total += len(raw)
        comp_total += len(comp)
    return ZstdDictionaryBatch(
        dict_sha256=dictionary.dict_sha256,
        dict_id=dictionary.dict_id,
        dict_bytes=dictionary.dict_bytes,
        record_digests=tuple(digests),
        compressed_records=tuple(compressed_list),
        uncompressed_total_bytes=raw_total,
        compressed_total_bytes=comp_total,
    )


def decompress_record_batch(
    batch: ZstdDictionaryBatch,
    *,
    max_record_bytes: int = 1024 * 1024,
) -> tuple[bytes, ...]:
    """Decompress and verify every record in a ``ZstdDictionaryBatch``."""
    if canonical_sha256(batch.dict_bytes) != batch.dict_sha256:
        raise ZstdCodecError("dictionary SHA-256 mismatch in ZstdDictionaryBatch")
    if len(batch.compressed_records) != len(batch.record_digests):
        raise ZstdCodecError("compressed_records and record_digests length mismatch")
    zdict = zstd.ZstdDict(batch.dict_bytes)
    if int(zdict.dict_id) != batch.dict_id:
        raise ZstdCodecError("dictionary ID mismatch in ZstdDictionaryBatch")
    restored: list[bytes] = []
    for comp, expected_digest in zip(batch.compressed_records, batch.record_digests, strict=True):
        raw = decompress_bytes(
            comp,
            max_output_size=max_record_bytes,
            expected_uncompressed_sha256=expected_digest,
            dictionary=zdict,
        )
        restored.append(raw)
    return tuple(restored)


def encode_zstd_text_armor(
    text: str,
    *,
    level: int = DEFAULT_ZSTD_LEVEL,
    dictionary: ZstdRecordDictionary | zstd.ZstdDict | None = None,
) -> str:
    """Compress UTF-8 ``text`` into a ``zstd1:<uncompressed_sha256>:<base64>`` string."""
    if not isinstance(text, str) or not text:
        raise ZstdCodecError("text MUST be a non-empty string")
    envelope = compress_bytes(text.encode("utf-8"), level=level, dictionary=dictionary)
    b64 = base64.b64encode(envelope.compressed_bytes).decode("ascii")
    return f"zstd1:{envelope.uncompressed_sha256}:{b64}"


def decode_zstd_text_armor(
    value: str,
    *,
    max_output_size: int = DEFAULT_MAX_OUTPUT_BYTES,
    expected_uncompressed_sha256: str | None = None,
    dictionary: ZstdRecordDictionary | zstd.ZstdDict | None = None,
) -> str:
    """Decode either a ``zstd1:<sha256>:<base64>`` armored string or a plain UTF-8 string."""
    if not isinstance(value, str) or not value:
        raise ZstdCodecError("value MUST be a non-empty string")
    if not value.startswith("zstd1:"):
        if expected_uncompressed_sha256 is not None:
            actual = canonical_sha256(value)
            expected = (
                expected_uncompressed_sha256
                if expected_uncompressed_sha256.startswith("sha256:")
                else f"sha256:{expected_uncompressed_sha256}"
            )
            if actual != expected:
                raise ZstdCodecError(
                    f"plain text SHA-256 mismatch: expected {expected}, got {actual}"
                )
        return value
    parts = value.split(":", 3)
    if len(parts) != 4 or parts[1] != "sha256" or len(parts[2]) != 64:
        raise ZstdCodecError("malformed zstd1 armor header")
    embedded_digest = f"sha256:{parts[2]}"
    if expected_uncompressed_sha256 is not None:
        normalized_expected = (
            expected_uncompressed_sha256
            if expected_uncompressed_sha256.startswith("sha256:")
            else f"sha256:{expected_uncompressed_sha256}"
        )
        if embedded_digest != normalized_expected:
            raise ZstdCodecError(
                f"zstd1 header digest mismatch: expected {normalized_expected}, "
                f"got {embedded_digest}"
            )
    try:
        compressed = base64.b64decode(parts[3].encode("ascii"), validate=True)
    except ValueError as exc:
        raise ZstdCodecError(f"invalid base64 in zstd1 armor: {exc}") from exc
    raw = decompress_bytes(
        compressed,
        max_output_size=max_output_size,
        expected_uncompressed_sha256=embedded_digest,
        dictionary=dictionary,
    )
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ZstdCodecError(f"decompressed zstd1 payload is not valid UTF-8: {exc}") from exc


def write_zstd_json(
    path: Path,
    payload: object,
    *,
    level: int = DEFAULT_ZSTD_LEVEL,
    sort_keys: bool = True,
) -> ZstdEnvelope:
    """Atomically write ``payload`` as Zstandard-compressed JSON to ``path``."""
    envelope = compress_json(payload, level=level, sort_keys=sort_keys)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_bytes(envelope.compressed_bytes)
    tmp_path.replace(path)
    return envelope


def read_zstd_json(
    path: Path,
    *,
    max_output_size: int = DEFAULT_MAX_OUTPUT_BYTES,
    expected_uncompressed_sha256: str | None = None,
) -> dict[str, Any]:
    """Read and validate a JSON object from either a ``.zst`` file or plain JSON file."""
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise ZstdCodecError(f"unable to read artifact {path}: {exc}") from exc
    if is_zstd_frame(raw_bytes):
        loaded = decompress_json(
            raw_bytes,
            max_output_size=max_output_size,
            expected_uncompressed_sha256=expected_uncompressed_sha256,
        )
    else:
        if len(raw_bytes) > max_output_size:
            raise ZstdCodecError(
                f"plain JSON file {path} exceeds max_output_size ({max_output_size} bytes)"
            )
        if expected_uncompressed_sha256 is not None:
            actual = canonical_sha256(raw_bytes)
            expected = (
                expected_uncompressed_sha256
                if expected_uncompressed_sha256.startswith("sha256:")
                else f"sha256:{expected_uncompressed_sha256}"
            )
            if actual != expected:
                raise ZstdCodecError(
                    f"uncompressed SHA-256 mismatch for {path}: expected {expected}, got {actual}"
                )
        try:
            loaded = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ZstdCodecError(f"invalid UTF-8 JSON in {path}: {exc}") from exc
    if not isinstance(loaded, Mapping):
        raise ZstdCodecError(f"expected JSON object in {path}")
    return cast(dict[str, Any], dict(loaded))


def _resolve_zstd_dict(
    dictionary: ZstdRecordDictionary | zstd.ZstdDict | None,
) -> zstd.ZstdDict | None:
    if dictionary is None:
        return None
    if isinstance(dictionary, ZstdRecordDictionary):
        return dictionary.as_zstd_dict()
    if isinstance(dictionary, zstd.ZstdDict):
        return dictionary
    raise ZstdCodecError("dictionary MUST be a ZstdRecordDictionary or zstd.ZstdDict")


__all__ = [
    "ARCHIVE_ZSTD_LEVEL",
    "DEFAULT_DICT_SIZE",
    "DEFAULT_MAX_OUTPUT_BYTES",
    "DEFAULT_ZSTD_LEVEL",
    "ZSTD_MAGIC",
    "ZstdCodecError",
    "ZstdDictionaryBatch",
    "ZstdEnvelope",
    "ZstdRecordDictionary",
    "canonical_sha256",
    "compress_bytes",
    "compress_json",
    "compress_record_batch",
    "decode_zstd_text_armor",
    "decompress_bytes",
    "decompress_json",
    "decompress_record_batch",
    "encode_zstd_text_armor",
    "is_zstd_frame",
    "read_zstd_json",
    "train_record_dictionary",
    "write_zstd_json",
]

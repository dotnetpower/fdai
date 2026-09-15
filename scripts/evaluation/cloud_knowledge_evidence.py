#!/usr/bin/env python3
"""Read bounded offline RAG observations and exclusively publish unverified diagnostics.

This adapter performs local file I/O only. The shared contract reducer owns numeric
accounting; neither module retrieves documents, calls a model, authenticates evidence,
verifies human approval, or grants production qualification. No shell is invoked.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import stat
import sys
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Final, NoReturn

if __package__ is None or __package__ == "":
    _REPO_ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(_REPO_ROOT / "packages/service-contracts/src"))

from fdai_service_contracts.cloud_knowledge import canonical_bytes
from fdai_service_contracts.cloud_knowledge_evaluation import (
    CloudKnowledgeEvaluationBatch,
    CloudKnowledgeEvaluationError,
    CloudKnowledgeEvaluationReport,
    evaluate_cloud_knowledge_evidence,
)

MAX_INPUT_BYTES: Final = 16 * 1024 * 1024
MAX_JSON_DEPTH: Final = 16
MAX_JSON_TOKENS: Final = 500_000
MAX_NUMBER_CHARACTERS: Final = 64
MAX_PATH_COMPONENTS: Final = 64


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CloudKnowledgeEvaluationError("evaluation JSON MUST NOT contain duplicate keys")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    raise CloudKnowledgeEvaluationError("evaluation JSON numbers MUST be finite")


def _integer(value: str) -> int:
    if len(value) > MAX_NUMBER_CHARACTERS:
        raise CloudKnowledgeEvaluationError("evaluation JSON number exceeds its token bound")
    return int(value)


def _float(value: str) -> float:
    if len(value) > MAX_NUMBER_CHARACTERS:
        raise CloudKnowledgeEvaluationError("evaluation JSON number exceeds its token bound")
    number = float(value)
    # JSON has already checked the token grammar. Inspect only the mantissa so
    # even a zero with an enormous exponent needs no Decimal exponent conversion.
    nonzero_mantissa = any(digit in "123456789" for digit in value.lower().partition("e")[0])
    if not math.isfinite(number) or (number == 0 and nonzero_mantissa):
        raise CloudKnowledgeEvaluationError("evaluation JSON number overflows or underflows")
    return number


def _json_budget(text: str) -> None:
    """Bound nesting and structural tokens before the JSON decoder allocates containers."""
    depth = 0
    tokens = 0
    quoted = False
    escaped = False
    for character in text:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
            continue
        if character == '"':
            quoted = True
        elif character in "[{":
            depth += 1
            tokens += 1
            if depth > MAX_JSON_DEPTH:
                raise CloudKnowledgeEvaluationError("evaluation JSON exceeds its nesting bound")
        elif character in "]}":
            depth -= 1
        elif character in ",:":
            tokens += 1
        if depth < 0 or tokens > MAX_JSON_TOKENS:
            raise CloudKnowledgeEvaluationError("evaluation JSON exceeds its structural bound")


def decode_evidence(content: bytes) -> CloudKnowledgeEvaluationBatch:
    """Decode finite, duplicate-free UTF-8 JSON under hard byte and structure ceilings.

    This is a syntax/shape boundary, not an authenticity check. Failures are
    content-free ``CloudKnowledgeEvaluationError`` values, including numeric overflow.
    """
    if not isinstance(content, bytes) or not 0 < len(content) <= MAX_INPUT_BYTES:
        raise CloudKnowledgeEvaluationError("evaluation input is empty or exceeds its byte bound")
    try:
        text = content.decode("utf-8")
        _json_budget(text)
        raw: object = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
            parse_int=_integer,
            parse_float=_float,
        )
        return CloudKnowledgeEvaluationBatch.model_validate(raw)
    except CloudKnowledgeEvaluationError:
        raise
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise CloudKnowledgeEvaluationError(
            "evaluation input MUST satisfy the closed UTF-8 JSON contracts"
        ) from None


def summarize_evidence(payload: Mapping[str, object]) -> dict[str, object]:
    """Return pure count-first diagnostics for an already decoded mapping, never approval."""
    try:
        batch = CloudKnowledgeEvaluationBatch.model_validate(payload)
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise CloudKnowledgeEvaluationError(
            "evaluation input MUST satisfy the closed contracts"
        ) from None
    return evaluate_cloud_knowledge_evidence(batch).model_dump(mode="json")


@contextmanager
def _parent_directory(path: Path) -> Iterator[tuple[int, str]]:
    """Pin each POSIX directory without following links, including intermediate components."""
    parts = path.parts[1:] if path.is_absolute() else path.parts
    if (
        not parts
        or len(parts) > MAX_PATH_COMPONENTS
        or ".." in parts
        or len(os.fsencode(path)) > 4096
    ):
        raise CloudKnowledgeEvaluationError("evaluation path MUST be bounded without traversal")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open(path.anchor if path.is_absolute() else ".", flags)
    try:
        for part in parts[:-1]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor, parts[-1]
    finally:
        os.close(descriptor)


def _read_input(path: Path) -> bytes:
    """Read one stable regular nonlinked file without blocking on a FIFO or device."""
    with _parent_directory(path) as (parent, name):
        descriptor = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent
        )
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or not 0 < before.st_size <= MAX_INPUT_BYTES
            ):
                raise CloudKnowledgeEvaluationError(
                    "evaluation input MUST be a bounded regular file without links"
                )
            content = stream.read(MAX_INPUT_BYTES + 1)
            after = os.fstat(stream.fileno())
            if (
                len(content) != before.st_size
                or after.st_size != before.st_size
                or after.st_mtime_ns != before.st_mtime_ns
                or after.st_ctime_ns != before.st_ctime_ns
            ):
                raise CloudKnowledgeEvaluationError("evaluation input changed while being read")
            return content


def evaluate_file(path: Path) -> CloudKnowledgeEvaluationReport:
    """Read a no-follow local input and reduce it offline; never create an output file."""
    try:
        batch = decode_evidence(_read_input(path))
    except (OSError, ValueError) as exc:
        if isinstance(exc, CloudKnowledgeEvaluationError):
            raise
        raise CloudKnowledgeEvaluationError(
            "evaluation input MUST be a readable no-follow regular file"
        ) from None
    return evaluate_cloud_knowledge_evidence(batch)


def _write_exclusive(path: Path, content: bytes) -> None:
    """Create only a new mode-0600 file; never truncate, replace, or unlink an existing path.

    All evaluation and serialization precede creation. An I/O failure may leave a
    private partial new file, which is not reported as successful and is not retried
    or automatically unlinked across an untrusted pathname race.
    """
    with _parent_directory(path) as (parent, name):
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=parent,
        )
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            written = stream.write(content)
            if written != len(content):
                raise CloudKnowledgeEvaluationError("evaluation output write was incomplete")
            stream.flush()
            os.fsync(stream.fileno())


def main(argv: Sequence[str] | None = None) -> int:
    """Publish canonical diagnostics; exit 0 for numeric pass, 1 for gaps, or 2 for invalid I/O.

    A zero exit code is not production qualification. Every report retains
    unverified authenticity, human review, and authorization with qualification false.
    """
    parser = argparse.ArgumentParser(
        description="Reduce offline RAG evidence; numeric success never qualifies production.",
        allow_abbrev=False,
    )
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = evaluate_file(args.receipt)
        encoded = canonical_bytes(report)
        if args.output is None:
            sys.stdout.write(encoded.decode("utf-8") + "\n")
        else:
            _write_exclusive(args.output, encoded)
    except CloudKnowledgeEvaluationError as exc:
        print(f"cloud knowledge evaluation failed: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError, RecursionError, OverflowError):
        print(
            "cloud knowledge evaluation failed: output MUST be a new writable no-follow file",
            file=sys.stderr,
        )
        return 2
    return 0 if report.numeric_status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

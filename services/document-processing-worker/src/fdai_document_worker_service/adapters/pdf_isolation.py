"""Process-isolated native PDF parsing with bounded CPU, memory, and output."""

from __future__ import annotations

import io
import json
import multiprocessing
from dataclasses import dataclass
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from typing import Final

import pypdf
from fdai_service_contracts import (
    DocumentExtractionUnavailableError,
    ExtractionUnavailableReason,
)
from pypdf.errors import PyPdfError

_DEFAULT_MEMORY_BYTES: Final[int] = 536_870_912
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 10.0
_DEFAULT_CPU_SECONDS: Final[int] = 5
_DEFAULT_MAX_PAGES: Final[int] = 512
_DEFAULT_MAX_CHARACTERS: Final[int] = 1_000_000
_DEFAULT_MAX_OUTPUT_BYTES: Final[int] = 8_000_000


@dataclass(frozen=True, slots=True)
class PdfIsolationPolicy:
    """Server-owned ceilings for one untrusted PDF parser process."""

    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    cpu_seconds: int = _DEFAULT_CPU_SECONDS
    memory_bytes: int = _DEFAULT_MEMORY_BYTES
    max_pages: int = _DEFAULT_MAX_PAGES
    max_characters: int = _DEFAULT_MAX_CHARACTERS
    max_output_bytes: int = _DEFAULT_MAX_OUTPUT_BYTES

    def __post_init__(self) -> None:
        if not 0.1 <= self.timeout_seconds <= 60:
            raise ValueError("PDF isolation timeout_seconds MUST be in [0.1, 60]")
        if not 1 <= self.cpu_seconds <= 30:
            raise ValueError("PDF isolation cpu_seconds MUST be in [1, 30]")
        if not 134_217_728 <= self.memory_bytes <= 2_147_483_648:
            raise ValueError("PDF isolation memory_bytes MUST be in [128 MiB, 2 GiB]")
        if not 1 <= self.max_pages <= 2_000:
            raise ValueError("PDF isolation max_pages MUST be in [1, 2000]")
        if not 1 <= self.max_characters <= 4_000_000:
            raise ValueError("PDF isolation max_characters MUST be in [1, 4000000]")
        if not 1_024 <= self.max_output_bytes <= 16_000_000:
            raise ValueError("PDF isolation max_output_bytes MUST be in [1024, 16000000]")


_DEFAULT_POLICY = PdfIsolationPolicy()


def extract_pdf_pages_isolated(
    content: bytes,
    *,
    policy: PdfIsolationPolicy = _DEFAULT_POLICY,
) -> tuple[str | None, ...]:
    """Parse native PDF text in a spawned process or return a typed unsafe-package failure."""

    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(
        target=_pdf_worker,
        args=(child, content, policy),
        name="fdai-pdf-parser",
        daemon=True,
    )
    try:
        process.start()
    except (OSError, RuntimeError):
        child.close()
        parent.close()
        raise _unavailable() from None
    child.close()
    try:
        if not parent.poll(policy.timeout_seconds):
            _stop(process)
            raise _unavailable()
        try:
            encoded = parent.recv_bytes(maxlength=policy.max_output_bytes)
            payload = json.loads(encoded.decode("utf-8"))
        except (EOFError, OSError, UnicodeError, json.JSONDecodeError):
            payload = {"status": "error"}
    finally:
        parent.close()
    process.join(timeout=1)
    if process.is_alive():
        _stop(process)
        raise _unavailable()
    if (
        process.exitcode != 0
        or not isinstance(payload, dict)
        or set(payload) != {"status", "pages"}
        or payload.get("status") != "ok"
        or not isinstance(payload.get("pages"), list)
        or any(item is not None and not isinstance(item, str) for item in payload["pages"])
    ):
        raise _unavailable()
    return tuple(payload["pages"])


def _pdf_worker(
    connection: Connection,
    content: bytes,
    policy: PdfIsolationPolicy,
) -> None:
    try:
        _apply_resource_limits(policy)
        reader = pypdf.PdfReader(io.BytesIO(content), strict=False)
        if reader.is_encrypted:
            raise ValueError("encrypted")
        if not 1 <= len(reader.pages) <= policy.max_pages:
            raise ValueError("page_budget")
        pages: list[str | None] = []
        characters = 0
        for page in reader.pages:
            text = (page.extract_text() or "").strip()
            characters += len(text)
            if characters > policy.max_characters:
                raise ValueError("text_budget")
            pages.append(text or None)
        _send_payload(connection, {"status": "ok", "pages": pages}, policy=policy)
    except (
        PyPdfError,
        AttributeError,
        MemoryError,
        OSError,
        RecursionError,
        TypeError,
        ValueError,
    ):
        _send_error(connection)
    finally:
        connection.close()


def _apply_resource_limits(policy: PdfIsolationPolicy) -> None:
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (policy.memory_bytes, policy.memory_bytes))
    resource.setrlimit(resource.RLIMIT_CPU, (policy.cpu_seconds, policy.cpu_seconds + 1))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _send_payload(
    connection: Connection,
    payload: dict[str, object],
    *,
    policy: PdfIsolationPolicy,
) -> None:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > policy.max_output_bytes:
        _send_error(connection)
        return
    try:
        connection.send_bytes(encoded)
    except (BrokenPipeError, OSError):
        return


def _send_error(connection: Connection) -> None:
    try:
        connection.send_bytes(b'{"status":"error"}')
    except (BrokenPipeError, OSError):
        return


def _stop(process: BaseProcess) -> None:
    process.terminate()
    process.join(timeout=1)
    if process.is_alive():
        process.kill()
        process.join(timeout=1)


def _unavailable() -> DocumentExtractionUnavailableError:
    return DocumentExtractionUnavailableError(ExtractionUnavailableReason.UNSAFE_PACKAGE)


__all__ = ["PdfIsolationPolicy", "extract_pdf_pages_isolated"]

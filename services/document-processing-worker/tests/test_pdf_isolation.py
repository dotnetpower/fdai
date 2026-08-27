"""Process isolation tests for untrusted native PDF parsing."""

from __future__ import annotations

import io
import json
import os
import time
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess

import pytest
from fdai_document_worker_service.adapters import pdf_isolation as pdf_isolation_module
from fdai_document_worker_service.adapters.pdf_isolation import (
    PdfIsolationPolicy,
    extract_pdf_pages_isolated,
)
from fdai_service_contracts import (
    DocumentExtractionUnavailableError,
    ExtractionUnavailableReason,
)
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def _sleeping_worker(*_args: object) -> None:
    time.sleep(1)


def _partial_frame_worker(connection: Connection, _policy: PdfIsolationPolicy) -> None:
    connection.recv_bytes()
    os.write(connection.fileno(), b"\x00\x00")
    time.sleep(1)


def _over_budget_worker(connection: Connection, _policy: PdfIsolationPolicy) -> None:
    connection.recv_bytes()
    connection.send_bytes(
        json.dumps(
            {"status": "ok", "pages": ["first", "second"]},
            separators=(",", ":"),
        ).encode()
    )
    connection.close()


def _pdf(text: str = "Native text", *, pages: int = 1) -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        stream = DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(output)
    return output.getvalue()


def test_native_pdf_text_returns_from_the_isolated_process() -> None:
    assert extract_pdf_pages_isolated(_pdf()) == ("Native text",)


def test_malformed_pdf_fails_closed_as_an_unsafe_package() -> None:
    with pytest.raises(DocumentExtractionUnavailableError) as unavailable:
        extract_pdf_pages_isolated(b"%PDF-malformed")

    assert unavailable.value.reason is ExtractionUnavailableReason.UNSAFE_PACKAGE


def test_page_budget_failure_isolated_from_the_worker() -> None:
    with pytest.raises(DocumentExtractionUnavailableError) as unavailable:
        extract_pdf_pages_isolated(
            _pdf(pages=2),
            policy=PdfIsolationPolicy(max_pages=1),
        )

    assert unavailable.value.reason is ExtractionUnavailableReason.UNSAFE_PACKAGE


def test_character_budget_failure_isolated_from_the_worker() -> None:
    with pytest.raises(DocumentExtractionUnavailableError) as unavailable:
        extract_pdf_pages_isolated(
            _pdf(text="too much text"),
            policy=PdfIsolationPolicy(max_characters=4),
        )

    assert unavailable.value.reason is ExtractionUnavailableReason.UNSAFE_PACKAGE


def test_encrypted_pdf_fails_closed_in_the_child() -> None:
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("test-password")
    writer.write(output)

    with pytest.raises(DocumentExtractionUnavailableError) as unavailable:
        extract_pdf_pages_isolated(output.getvalue())

    assert unavailable.value.reason is ExtractionUnavailableReason.UNSAFE_PACKAGE


def test_wall_timeout_terminates_the_parser_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf_isolation_module, "_pdf_worker", _sleeping_worker)

    with pytest.raises(DocumentExtractionUnavailableError) as unavailable:
        extract_pdf_pages_isolated(
            _pdf(),
            policy=PdfIsolationPolicy(timeout_seconds=0.1),
        )

    assert unavailable.value.reason is ExtractionUnavailableReason.UNSAFE_PACKAGE


def test_wall_timeout_includes_input_transfer_and_partial_frame_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pdf_isolation_module, "_pdf_worker", _partial_frame_worker)
    started = time.monotonic()

    with pytest.raises(DocumentExtractionUnavailableError) as unavailable:
        extract_pdf_pages_isolated(
            b"x" * (25 * 1024 * 1024),
            policy=PdfIsolationPolicy(timeout_seconds=0.1),
        )

    assert time.monotonic() - started < 0.75
    assert unavailable.value.reason is ExtractionUnavailableReason.UNSAFE_PACKAGE


def test_parent_rejects_valid_json_that_exceeds_page_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pdf_isolation_module, "_pdf_worker", _over_budget_worker)

    with pytest.raises(DocumentExtractionUnavailableError) as unavailable:
        extract_pdf_pages_isolated(
            _pdf(),
            policy=PdfIsolationPolicy(max_pages=1),
        )

    assert unavailable.value.reason is ExtractionUnavailableReason.UNSAFE_PACKAGE


def test_ipc_thread_start_failure_stops_the_parser_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stopped = False
    original_stop = pdf_isolation_module._stop

    def fail_start(_thread: object) -> None:
        raise RuntimeError("thread unavailable")

    def record_stop(process: BaseProcess) -> None:
        nonlocal stopped
        stopped = True
        original_stop(process)

    monkeypatch.setattr(pdf_isolation_module, "_start_exchange_thread", fail_start)
    monkeypatch.setattr(pdf_isolation_module, "_stop", record_stop)

    with pytest.raises(DocumentExtractionUnavailableError):
        extract_pdf_pages_isolated(_pdf())

    assert stopped is True

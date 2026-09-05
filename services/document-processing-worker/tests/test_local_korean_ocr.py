"""Bounded local Korean OCR provider tests."""

from __future__ import annotations

import unicodedata

import pytest
from fdai_document_worker_service.adapters import local_ocr
from fdai_document_worker_service.adapters.local_ocr import (
    LocalKoreanOcr,
    LocalOcrConfig,
    LocalOcrLine,
)
from fdai_service_contracts import AdapterReadinessState


def test_local_ocr_configuration_rejects_unbounded_values() -> None:
    with pytest.raises(ValueError, match="max_pages"):
        LocalOcrConfig(max_pages=0)
    with pytest.raises(ValueError, match="languages"):
        LocalOcrConfig(languages="kor;curl")


async def test_local_ocr_readiness_requires_korean_and_english(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(local_ocr, "_available_languages", lambda: frozenset({"eng"}))
    unavailable = await LocalKoreanOcr().probe_readiness()
    monkeypatch.setattr(
        local_ocr,
        "_available_languages",
        lambda: frozenset({"eng", "kor"}),
    )
    ready = await LocalKoreanOcr().probe_readiness()
    assert unavailable.state is AdapterReadinessState.UNAVAILABLE
    assert unavailable.reason == "language_data_unavailable"
    assert ready.state is AdapterReadinessState.READY
    assert ready.live_verified


async def test_local_ocr_normalizes_korean_output_to_nfc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decomposed = unicodedata.normalize("NFD", "장애 조치")
    monkeypatch.setattr(
        local_ocr,
        "run_local_ocr_isolated",
        lambda _content, _media_type, _config: (
            LocalOcrLine(page=1, line=1, text=f"  {decomposed}  "),
        ),
    )
    provider = LocalKoreanOcr()
    version = type("Version", (), {"media_type": "image/png"})()
    units = await provider.extract(version=version, content=b"png")  # type: ignore[arg-type]
    assert units[0].text == "장애 조치"
    assert units[0].locator == "page:1:line:1"


def test_local_ocr_rejects_invalid_child_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(local_ocr.multiprocessing, "get_context", lambda _method: _Context())
    with pytest.raises(RuntimeError, match="invalid line"):
        local_ocr.run_local_ocr_isolated(b"image", "image/png", LocalOcrConfig())


class _Context:
    def Pipe(self, *, duplex: bool) -> tuple[_Connection, _Connection]:  # noqa: N802
        assert duplex
        return _Connection(), _Connection()

    def Process(self, **_kwargs: object) -> _Process:  # noqa: N802
        return _Process()


class _Connection:
    def close(self) -> None:
        return None

    def send_bytes(self, _value: bytes) -> None:
        return None

    def recv_bytes(self, *, maxlength: int | None = None) -> bytes:
        del maxlength
        return b'[{"page":1,"line":1,"text":7}]'


class _Process:
    exitcode = 0

    def start(self) -> None:
        return None

    def join(self, *, timeout: float) -> None:
        del timeout

    def is_alive(self) -> bool:
        return False

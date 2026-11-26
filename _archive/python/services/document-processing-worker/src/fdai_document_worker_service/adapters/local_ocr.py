"""Process-isolated Korean and English OCR for local document extraction."""

from __future__ import annotations

import asyncio
import io
import json
import multiprocessing
import queue
import shutil
import threading
import time
import unicodedata
from dataclasses import asdict, dataclass
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from typing import Final

from fdai_service_contracts import (
    AdapterReadiness,
    DocumentVersion,
    ProviderUnavailableError,
    StructuralUnit,
    configured_readiness,
    live_readiness,
    live_unavailable_readiness,
)

_DEFAULT_MEMORY_BYTES: Final = 805_306_368
_DEFAULT_MAX_OUTPUT_BYTES: Final = 8_000_000


@dataclass(frozen=True, slots=True)
class LocalOcrConfig:
    """Server-owned resource and output bounds for one local OCR operation."""

    languages: str = "kor+eng"
    timeout_seconds: float = 30.0
    cpu_seconds: int = 20
    memory_bytes: int = _DEFAULT_MEMORY_BYTES
    max_pages: int = 20
    max_pixels_per_page: int = 16_000_000
    max_lines: int = 5_000
    max_characters: int = 1_000_000
    max_output_bytes: int = _DEFAULT_MAX_OUTPUT_BYTES
    pdf_dpi: int = 200

    def __post_init__(self) -> None:
        if not self.languages or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789_+"
            for character in self.languages
        ):
            raise ValueError("local OCR languages MUST use Tesseract language tokens")
        if not 1 <= self.timeout_seconds <= 300:
            raise ValueError("local OCR timeout_seconds MUST be in [1, 300]")
        if not 1 <= self.cpu_seconds <= 120:
            raise ValueError("local OCR cpu_seconds MUST be in [1, 120]")
        if not 268_435_456 <= self.memory_bytes <= 2_147_483_648:
            raise ValueError("local OCR memory_bytes MUST be in [256 MiB, 2 GiB]")
        if not 1 <= self.max_pages <= 200:
            raise ValueError("local OCR max_pages MUST be in [1, 200]")
        if not 1_000_000 <= self.max_pixels_per_page <= 64_000_000:
            raise ValueError("local OCR max_pixels_per_page MUST be in [1000000, 64000000]")
        if not 1 <= self.max_lines <= 100_000:
            raise ValueError("local OCR max_lines MUST be in [1, 100000]")
        if not 1 <= self.max_characters <= 4_000_000:
            raise ValueError("local OCR max_characters MUST be in [1, 4000000]")
        if not 1_024 <= self.max_output_bytes <= 16_000_000:
            raise ValueError("local OCR max_output_bytes MUST be in [1024, 16000000]")
        if not 72 <= self.pdf_dpi <= 300:
            raise ValueError("local OCR pdf_dpi MUST be in [72, 300]")


class LocalKoreanOcr:
    """Extract Korean and English text without network access or runtime model downloads."""

    def __init__(self, config: LocalOcrConfig | None = None) -> None:
        self._config = config or LocalOcrConfig()

    def readiness(self) -> AdapterReadiness:
        return configured_readiness("local-korean-ocr")

    async def probe_readiness(self) -> AdapterReadiness:
        try:
            available = await asyncio.to_thread(_available_languages)
        except Exception as exc:  # noqa: BLE001 - expose only safe exception type
            return live_unavailable_readiness(
                "local-korean-ocr", f"probe_failed:{type(exc).__name__}"
            )
        required = frozenset(self._config.languages.split("+"))
        if not required.issubset(available):
            return live_unavailable_readiness("local-korean-ocr", "language_data_unavailable")
        return live_readiness("local-korean-ocr")

    async def extract(
        self,
        *,
        version: DocumentVersion,
        content: bytes,
    ) -> tuple[StructuralUnit, ...]:
        try:
            payload = await asyncio.to_thread(
                run_local_ocr_isolated,
                content,
                version.media_type,
                self._config,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise ProviderUnavailableError(
                "local Korean OCR failed within configured bounds"
            ) from exc
        return tuple(
            StructuralUnit(
                unit_id=f"ocr-page-{line.page}-line-{line.line}",
                kind="page",
                locator=f"page:{line.page}:line:{line.line}",
                text=text,
            )
            for line in payload
            if (text := _normalize_text(line.text))
        )


@dataclass(frozen=True, slots=True)
class LocalOcrLine:
    page: int
    line: int
    text: str


def run_local_ocr_isolated(
    content: bytes,
    media_type: str,
    config: LocalOcrConfig,
) -> tuple[LocalOcrLine, ...]:
    """Run rasterization and OCR in one resource-limited child process."""
    deadline = time.monotonic() + config.timeout_seconds
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=True)
    process = context.Process(
        target=_ocr_worker,
        args=(child, config),
        name="fdai-local-ocr",
        daemon=True,
    )
    try:
        process.start()
    except (OSError, RuntimeError):
        child.close()
        parent.close()
        raise RuntimeError("local OCR process could not start") from None
    child.close()
    exchange_result: queue.Queue[bytes | None] = queue.Queue(maxsize=1)
    exchange = threading.Thread(
        target=_exchange_payload,
        args=(parent, content, media_type, config.max_output_bytes, exchange_result),
        name="fdai-local-ocr-ipc",
        daemon=True,
    )
    exchange.start()
    try:
        exchange.join(timeout=max(0.0, deadline - time.monotonic()))
        if exchange.is_alive():
            _stop(process)
            raise RuntimeError("local OCR timed out")
        encoded = exchange_result.get_nowait()
    finally:
        parent.close()
    process.join(timeout=max(0.0, deadline - time.monotonic()))
    if process.is_alive():
        _stop(process)
        raise RuntimeError("local OCR timed out")
    if process.exitcode != 0 or encoded is None:
        raise RuntimeError("local OCR child failed")
    try:
        raw = json.loads(encoded.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("local OCR returned malformed output") from exc
    if not isinstance(raw, list) or len(raw) > config.max_lines:
        raise RuntimeError("local OCR returned invalid line count")
    lines: list[LocalOcrLine] = []
    characters = 0
    for item in raw:
        if (
            not isinstance(item, dict)
            or set(item) != {"page", "line", "text"}
            or not isinstance(item["page"], int)
            or not isinstance(item["line"], int)
            or not isinstance(item["text"], str)
            or item["page"] < 1
            or item["line"] < 1
        ):
            raise RuntimeError("local OCR returned an invalid line")
        text = _normalize_text(item["text"])
        if not text:
            continue
        characters += len(text)
        if characters > config.max_characters:
            raise RuntimeError("local OCR text exceeded configured bounds")
        lines.append(LocalOcrLine(item["page"], item["line"], text))
    return tuple(lines)


def _ocr_worker(connection: Connection, config: LocalOcrConfig) -> None:
    try:
        _apply_resource_limits(config)
        media_type = connection.recv_bytes(maxlength=256).decode("ascii")
        content = connection.recv_bytes()
        result = _extract_sync(content, media_type=media_type, config=config)
        encoded = json.dumps(
            [asdict(line) for line in result],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > config.max_output_bytes:
            raise ValueError("local OCR output exceeded configured bounds")
        connection.send_bytes(encoded)
    except Exception:  # noqa: BLE001 - child returns no sensitive parser detail
        try:
            connection.send_bytes(b"")
        except (BrokenPipeError, OSError):
            pass
    finally:
        connection.close()


def _extract_sync(
    content: bytes,
    *,
    media_type: str,
    config: LocalOcrConfig,
) -> tuple[LocalOcrLine, ...]:
    import pypdfium2  # type: ignore[import-untyped]
    import pytesseract  # type: ignore[import-untyped]
    from PIL import Image, ImageSequence
    from pytesseract import Output

    images: list[object] = []
    if media_type == "application/pdf":
        document = pypdfium2.PdfDocument(content)
        try:
            if not 1 <= len(document) <= config.max_pages:
                raise ValueError("local OCR PDF page count is outside configured bounds")
            scale = config.pdf_dpi / 72
            for page_number in range(len(document)):
                page = document[page_number]
                try:
                    image = page.render(scale=scale).to_pil()
                finally:
                    page.close()
                _validate_image(image, config)
                images.append(image)
        finally:
            document.close()
    else:
        source = Image.open(io.BytesIO(content))
        try:
            frames = list(ImageSequence.Iterator(source))
            if not 1 <= len(frames) <= config.max_pages:
                raise ValueError("local OCR image frame count is outside configured bounds")
            for frame in frames:
                image = frame.copy().convert("RGB")
                _validate_image(image, config)
                images.append(image)
        finally:
            source.close()

    lines: list[LocalOcrLine] = []
    characters = 0
    for page_number, image in enumerate(images, start=1):
        data = pytesseract.image_to_data(
            image,
            lang=config.languages,
            config="--oem 1 --psm 6",
            output_type=Output.DICT,
            timeout=config.timeout_seconds,
        )
        grouped: dict[tuple[int, int, int], list[str]] = {}
        for index, raw in enumerate(data["text"]):
            text = _normalize_text(str(raw))
            if not text:
                continue
            key = (
                int(data["block_num"][index]),
                int(data["par_num"][index]),
                int(data["line_num"][index]),
            )
            grouped.setdefault(key, []).append(text)
        for line_number, key in enumerate(sorted(grouped), start=1):
            text = _normalize_text(" ".join(grouped[key]))
            characters += len(text)
            if len(lines) >= config.max_lines or characters > config.max_characters:
                raise ValueError("local OCR output exceeded configured bounds")
            lines.append(LocalOcrLine(page_number, line_number, text))
    return tuple(lines)


def _validate_image(image: object, config: LocalOcrConfig) -> None:
    size = getattr(image, "size", None)
    if (
        not isinstance(size, tuple)
        or len(size) != 2
        or not all(isinstance(value, int) and value > 0 for value in size)
        or size[0] * size[1] > config.max_pixels_per_page
    ):
        raise ValueError("local OCR image dimensions exceed configured bounds")


def _available_languages() -> frozenset[str]:
    if shutil.which("tesseract") is None:
        return frozenset()
    import pytesseract

    return frozenset(pytesseract.get_languages(config=""))


def _normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def _exchange_payload(
    connection: Connection,
    content: bytes,
    media_type: str,
    maximum: int,
    result: queue.Queue[bytes | None],
) -> None:
    try:
        connection.send_bytes(media_type.encode("ascii"))
        connection.send_bytes(content)
        result.put(connection.recv_bytes(maxlength=maximum))
    except (EOFError, OSError, UnicodeError):
        result.put(None)


def _apply_resource_limits(config: LocalOcrConfig) -> None:
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (config.memory_bytes, config.memory_bytes))
    resource.setrlimit(resource.RLIMIT_CPU, (config.cpu_seconds, config.cpu_seconds + 1))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _stop(process: BaseProcess) -> None:
    if not process.is_alive():
        process.join(timeout=0)
        return
    process.terminate()
    process.join(timeout=1)
    if process.is_alive():
        process.kill()
        process.join(timeout=1)

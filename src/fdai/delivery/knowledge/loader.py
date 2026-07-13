"""File-system loader for Knowledge Base ingestion.

Turns local files (a console upload landing in a drop directory, a repo of
runbooks, a committed **resource plan**) into
:class:`~fdai.shared.providers.knowledge.KnowledgeDocument` records ready to
hand to :meth:`KnowledgeSource.ingest` /
:meth:`~fdai.core.knowledge.registry.KnowledgeRegistry.register`.

This is the delivery-side counterpart of
:class:`~fdai.shared.providers.manual_source.DropDirectoryManualSource`
(which feeds the rule distiller): one generic file adapter covers every
credential-free ingestion mode - an operator drop, a console upload, an
email-in gateway - because they all land a file on disk.

Scope and boundaries
--------------------

- **Text formats only upstream.** Plain-text sources (``.md``, ``.txt``,
  ``.rst``) and infrastructure/plan text (``.tf``, ``.tfvars``, ``.json``,
  ``.yaml``, ``.yml``, ``.rego``) are read directly. Binary office formats
  (``.pdf`` / ``.docx`` / ``.pptx``) need a converter dependency and are a
  fork concern - an unknown or binary extension is skipped, never guessed.
- **Fail-safe.** An oversized file, an undecodable (binary) file, or an
  unreadable path is skipped with a warning; one bad file never aborts a
  batch. The caller ingests whatever loaded cleanly.
- **Secret-safe / customer-agnostic.** ``doc_id`` and ``source_ref`` are the
  path **relative to the root**, so an absolute host path never leaks into a
  citation or audit entry. The file body is the document text; the caller is
  responsible for not dropping secret-bearing files into the root.
- **Deterministic.** Files are visited in sorted order and ``doc_id`` is the
  stable relative POSIX path, so re-loading the same tree upserts in place
  (the ``KnowledgeSource`` keys chunks on ``doc_id``).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from fdai.shared.providers.knowledge import KnowledgeDocument

_LOGGER = logging.getLogger("fdai.delivery.knowledge.loader")

#: Text extensions read directly upstream. Binary office formats need a
#: converter and are a fork concern.
DEFAULT_TEXT_SUFFIXES: frozenset[str] = frozenset(
    {
        ".md",
        ".txt",
        ".rst",
        ".tf",
        ".tfvars",
        ".json",
        ".yaml",
        ".yml",
        ".rego",
    }
)

#: SRE-agent parity: a 16 MB per-file ceiling. A larger file is skipped.
DEFAULT_MAX_BYTES: int = 16 * 1024 * 1024


def load_knowledge_documents(
    root: Path | str,
    *,
    suffixes: frozenset[str] = DEFAULT_TEXT_SUFFIXES,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> list[KnowledgeDocument]:
    """Load every supported text file under ``root`` into documents.

    Recurses ``root`` in sorted order, reads each file whose suffix is in
    ``suffixes`` and whose size is at most ``max_bytes``, and builds a
    :class:`KnowledgeDocument` whose ``doc_id`` / ``source_ref`` is the path
    relative to ``root``. A single file that is oversized, binary
    (undecodable UTF-8), or unreadable is skipped with a warning rather than
    raising, so a batch never fails on one bad file.

    A ``root`` that does not exist or is not a directory yields ``[]`` - an
    unconfigured drop directory is "nothing to ingest", not an error.
    """
    if max_bytes < 1:
        raise ValueError("max_bytes MUST be >= 1")

    root_path = Path(root)
    if not root_path.is_dir():
        _LOGGER.info("knowledge root %s is not a directory; nothing to load", root_path)
        return []

    documents: list[KnowledgeDocument] = []
    for path in sorted(root_path.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in suffixes:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            _LOGGER.warning("cannot stat %s; skipping", path, exc_info=True)
            continue
        if size > max_bytes:
            _LOGGER.warning("skipping %s: %d bytes exceeds max_bytes=%d", path, size, max_bytes)
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            _LOGGER.warning("cannot read %s as UTF-8 text; skipping", path, exc_info=True)
            continue
        if not text.strip():
            continue
        rel = path.relative_to(root_path).as_posix()
        documents.append(
            KnowledgeDocument(
                doc_id=rel,
                text=text,
                source_ref=rel,
                metadata={"suffix": path.suffix.lower(), "bytes": str(size)},
            )
        )
    return documents


def documents_from_files(
    paths: Sequence[Path | str],
    *,
    root: Path | str,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> list[KnowledgeDocument]:
    """Load an explicit list of files (e.g. a single console upload).

    Like :func:`load_knowledge_documents` but for a caller-supplied file
    list rather than a directory walk. ``root`` anchors the relative
    ``doc_id`` / ``source_ref`` so uploads keep stable, host-path-free ids.
    A path outside ``root``, oversized, binary, or unreadable is skipped.
    """
    if max_bytes < 1:
        raise ValueError("max_bytes MUST be >= 1")

    root_path = Path(root)
    documents: list[KnowledgeDocument] = []
    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            _LOGGER.warning("not a file: %s; skipping", path)
            continue
        try:
            rel = path.resolve().relative_to(root_path.resolve()).as_posix()
        except ValueError:
            _LOGGER.warning("%s is outside root %s; skipping", path, root_path)
            continue
        try:
            size = path.stat().st_size
        except OSError:
            _LOGGER.warning("cannot stat %s; skipping", path, exc_info=True)
            continue
        if size > max_bytes:
            _LOGGER.warning("skipping %s: %d bytes exceeds max_bytes=%d", path, size, max_bytes)
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            _LOGGER.warning("cannot read %s as UTF-8 text; skipping", path, exc_info=True)
            continue
        if not text.strip():
            continue
        documents.append(
            KnowledgeDocument(
                doc_id=rel,
                text=text,
                source_ref=rel,
                metadata={"suffix": path.suffix.lower(), "bytes": str(size)},
            )
        )
    return documents


__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_TEXT_SUFFIXES",
    "documents_from_files",
    "load_knowledge_documents",
]

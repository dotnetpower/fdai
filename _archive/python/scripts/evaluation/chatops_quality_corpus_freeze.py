#!/usr/bin/env python3
"""Freeze a restricted ChatOps corpus into a content-free public manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

if __package__ is None or __package__ == "":
    _REPO_ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(_REPO_ROOT))
    sys.path.insert(0, str(_REPO_ROOT / "services/core-control-plane/src"))

from fdai.core.conversation_assurance.quality_scorecard import (
    CHATOPS_QUALITY_CONTRACT_V1,
)
from scripts.evaluation.chatops_quality_corpus import (
    CorpusManifestError,
    HiddenCorpusManifest,
    manifest_payload,
    summary,
)
from scripts.evaluation.chatops_quality_corpus_manifest import (
    load_manifest,
    parse_manifest,
)

_MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
_MAX_CONTENT_BYTES = 64 * 1024
_MAX_LABEL_BYTES = 64 * 1024
_ROOT_KEYS = frozenset(
    {
        "schema_version",
        "corpus_id",
        "corpus_version",
        "frozen_at",
        "freeze_revision",
        "restricted_artifact_id",
        "review_protocol",
        "rubric_observation_floors",
        "cases",
    }
)
_CASE_KEYS = frozenset(
    {
        "case_id",
        "conversation_id",
        "turn_index",
        "locale",
        "content",
        "label",
        "tags",
        "rubric_item_ids",
    }
)


def freeze_restricted_artifact(path: Path) -> HiddenCorpusManifest:
    """Build a validated public manifest without returning restricted values."""

    raw = _load_private_json(path)
    root = _mapping(raw, "restricted artifact")
    _exact_keys(root, _ROOT_KEYS, "restricted artifact")
    if _integer(root["schema_version"], "schema_version") != 1:
        raise CorpusManifestError("restricted artifact schema_version MUST be 1")
    cases = _array(root["cases"], "cases")
    public_cases = [_public_case(value, index) for index, value in enumerate(cases)]
    contract = CHATOPS_QUALITY_CONTRACT_V1
    public = {
        "schema_version": 1,
        "corpus_id": _string(root["corpus_id"], "corpus_id"),
        "corpus_version": _string(root["corpus_version"], "corpus_version"),
        "frozen_at": _string(root["frozen_at"], "frozen_at"),
        "freeze_revision": _string(root["freeze_revision"], "freeze_revision"),
        "qualification_contract_version": contract.version,
        "qualification_contract_digest": contract.content_digest,
        "restricted_artifact_id": _string(
            root["restricted_artifact_id"],
            "restricted_artifact_id",
        ),
        "hidden_payload_digest": _digest(root),
        "review_protocol": root["review_protocol"],
        "rubric_observation_floors": root["rubric_observation_floors"],
        "cases": public_cases,
    }
    return parse_manifest(public)


def write_public_manifest(
    manifest: HiddenCorpusManifest,
    output: Path,
) -> bool:
    """Create a public manifest once; an existing different version is immutable."""

    if output.is_symlink():
        raise CorpusManifestError("public manifest output MUST NOT be a symbolic link")
    if output.exists():
        existing = load_manifest(output)
        if existing.content_digest == manifest.content_digest:
            return False
        raise CorpusManifestError(
            "public manifest output already contains a different frozen manifest"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            manifest_payload(manifest),
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.",
        suffix=".tmp",
        dir=output.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        try:
            os.link(temporary, output)
        except FileExistsError:
            existing = load_manifest(output)
            if existing.content_digest == manifest.content_digest:
                return False
            raise CorpusManifestError(
                "public manifest output changed during the freeze operation"
            ) from None
        directory_descriptor = os.open(
            output.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        return True
    finally:
        temporary.unlink(missing_ok=True)


def _load_private_json(path: Path) -> object:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as exc:
        raise CorpusManifestError("restricted artifact is unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise CorpusManifestError("restricted artifact MUST be a regular file")
        if metadata.st_mode & 0o077:
            raise CorpusManifestError("restricted artifact permissions MUST be owner-only")
        if metadata.st_size > _MAX_ARTIFACT_BYTES:
            raise CorpusManifestError("restricted artifact exceeds the maximum size")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw_bytes = stream.read(_MAX_ARTIFACT_BYTES + 1)
        if len(raw_bytes) > _MAX_ARTIFACT_BYTES:
            raise CorpusManifestError("restricted artifact exceeds the maximum size")
        text = raw_bytes.decode("utf-8")
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CorpusManifestError("restricted artifact is unreadable") from exc
    finally:
        os.close(descriptor)


def _public_case(raw: object, index: int) -> dict[str, object]:
    field = f"cases[{index}]"
    value = _mapping(raw, field)
    _exact_keys(value, _CASE_KEYS, field)
    case_id = _string(value["case_id"], f"{field}.case_id")
    content = _string(value["content"], f"{field}.content")
    if len(content.encode()) > _MAX_CONTENT_BYTES:
        raise CorpusManifestError(f"{field}.content exceeds the maximum size")
    label = _mapping(value["label"], f"{field}.label")
    if not label:
        raise CorpusManifestError(f"{field}.label MUST be a non-empty object")
    if len(_canonical(label)) > _MAX_LABEL_BYTES:
        raise CorpusManifestError(f"{field}.label exceeds the maximum size")
    return {
        "case_id": case_id,
        "conversation_id": _string(
            value["conversation_id"],
            f"{field}.conversation_id",
        ),
        "turn_index": _integer(value["turn_index"], f"{field}.turn_index"),
        "locale": _string(value["locale"], f"{field}.locale"),
        "content_commitment": _digest(content),
        "label_commitment": _digest({"case_id": case_id, "label": label}),
        "tags": _array(value["tags"], f"{field}.tags"),
        "rubric_item_ids": _array(
            value["rubric_item_ids"],
            f"{field}.rubric_item_ids",
        ),
    }


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise CorpusManifestError("restricted artifact contains a duplicate object key")
        value[key] = item
    return value


def _reject_json_constant(_: str) -> object:
    raise CorpusManifestError("restricted artifact contains a non-finite number")


def _mapping(raw: object, field: str) -> Mapping[str, Any]:
    if not isinstance(raw, dict) or any(not isinstance(key, str) for key in raw):
        raise CorpusManifestError(f"{field} MUST be an object with string keys")
    return raw


def _array(raw: object, field: str) -> list[object]:
    if not isinstance(raw, list):
        raise CorpusManifestError(f"{field} MUST be an array")
    return raw


def _exact_keys(raw: Mapping[str, Any], expected: frozenset[str], field: str) -> None:
    actual = frozenset(raw)
    if actual != expected:
        raise CorpusManifestError(f"{field} fields differ from the restricted schema")


def _string(raw: object, field: str) -> str:
    if not isinstance(raw, str):
        raise CorpusManifestError(f"{field} MUST be a string")
    return raw


def _integer(raw: object, field: str) -> int:
    if type(raw) is not int:
        raise CorpusManifestError(f"{field} MUST be an integer")
    return raw


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restricted-artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = freeze_restricted_artifact(args.restricted_artifact)
        created = write_public_manifest(manifest, args.output)
    except CorpusManifestError as exc:
        print(f"chatops-quality-corpus-freeze: FAIL {exc}", file=sys.stderr)
        return 1
    receipt = summary(manifest)
    receipt["public_manifest_created"] = created
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

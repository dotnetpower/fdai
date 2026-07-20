"""Canonical durable skill bundle codec tests."""

from __future__ import annotations

import base64
import hashlib
import json

import pytest
import yaml

from fdai.core.skills import skill_body_digest
from fdai.core.supply_chain.skill_bundle import (
    MAX_ENCODED_SKILL_BUNDLE_BYTES,
    SkillBundleCodecError,
    decode_skill_bundle,
    encode_skill_bundle,
)


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "references/../guide.txt",
        "references\\guide.txt",
    ],
)
def test_decoder_rejects_filesystem_paths(path: str) -> None:
    raw = _skill(((path, b"guide"),))
    document = {
        "kind": "fdai.skill-bundle",
        "markdown": raw.decode(),
        "references": [{"content": base64.b64encode(b"guide").decode(), "path": path}],
        "version": 1,
    }

    with pytest.raises(SkillBundleCodecError, match="safe path"):
        decode_skill_bundle(json.dumps(document, sort_keys=True, separators=(",", ":")).encode())


def test_decoder_rejects_symlink_like_reference_metadata() -> None:
    raw = _skill((("references/guide.txt", b"guide"),))
    document = json.loads(encode_skill_bundle(raw, {"references/guide.txt": b"guide"}).decode())
    document["references"][0]["link_target"] = "references/other.txt"

    with pytest.raises(SkillBundleCodecError, match="unknown keys"):
        decode_skill_bundle(json.dumps(document, sort_keys=True, separators=(",", ":")).encode())


def _skill(references: tuple[tuple[str, bytes], ...] = ()) -> bytes:
    body = "Use deterministic tools only."
    manifest: dict[str, object] = {
        "name": "example.skill",
        "version": "1.0.0",
        "description": "Example",
        "source": "publisher.example",
        "body_sha256": skill_body_digest(body),
        "required_tools": [],
        "allowed_agents": [],
    }
    if references:
        manifest["references"] = [
            {
                "path": path,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
                "media_type": "application/octet-stream",
            }
            for path, content in references
        ]
    return f"---\n{yaml.safe_dump(manifest, sort_keys=False)}---\n{body}\n".encode()


def test_bundle_round_trip_is_canonical_deterministic_and_immutable() -> None:
    references = {
        "references/z.bin": b"\xff\x00",
        "references/a.txt": b"exact UTF-8 content",
    }
    raw = _skill(tuple(references.items()))

    first = encode_skill_bundle(raw, references)
    second = encode_skill_bundle(raw, dict(reversed(tuple(references.items()))))
    decoded = decode_skill_bundle(first)

    assert first == second
    assert decoded.raw_markdown == raw
    assert dict(decoded.references) == references
    with pytest.raises(TypeError):
        decoded.references["references/new.txt"] = b"blocked"  # type: ignore[index]


def test_legacy_raw_markdown_decodes_only_without_references() -> None:
    raw = _skill()

    decoded = decode_skill_bundle(raw)

    assert decoded.raw_markdown == raw
    assert dict(decoded.references) == {}
    with pytest.raises(SkillBundleCodecError, match="missing references"):
        decode_skill_bundle(_skill((("references/guide.txt", b"guide"),)))


@pytest.mark.parametrize(
    "mutation",
    [
        {"kind": "other"},
        {"version": 2},
        {"extra": True},
    ],
)
def test_wrong_kind_version_and_unknown_keys_are_rejected(mutation: dict[str, object]) -> None:
    document = json.loads(encode_skill_bundle(_skill(), {}).decode())
    document.update(mutation)

    with pytest.raises(SkillBundleCodecError):
        decode_skill_bundle(json.dumps(document, sort_keys=True, separators=(",", ":")).encode())


def test_duplicate_json_key_and_noncanonical_json_are_rejected() -> None:
    encoded = encode_skill_bundle(_skill(), {})
    duplicate = encoded.replace(b'{"kind":', b'{"kind":"fdai.skill-bundle","kind":', 1)

    with pytest.raises(SkillBundleCodecError, match="duplicate key"):
        decode_skill_bundle(duplicate)
    with pytest.raises(SkillBundleCodecError, match="canonical"):
        decode_skill_bundle(b" " + encoded)


@pytest.mark.parametrize("content", ["not base64!", "\u2603"])
def test_malformed_base64_is_rejected(content: str) -> None:
    raw = _skill((("references/guide.txt", b"guide"),))
    document = json.loads(encode_skill_bundle(raw, {"references/guide.txt": b"guide"}).decode())
    document["references"][0]["content"] = content

    with pytest.raises(SkillBundleCodecError, match="base64"):
        decode_skill_bundle(json.dumps(document, sort_keys=True, separators=(",", ":")).encode())


@pytest.mark.parametrize("mode", ["missing", "extra", "duplicate"])
def test_reference_path_set_must_match_manifest(mode: str) -> None:
    raw = _skill((("references/guide.txt", b"guide"),))
    document = json.loads(encode_skill_bundle(raw, {"references/guide.txt": b"guide"}).decode())
    if mode == "missing":
        document["references"] = []
    elif mode == "extra":
        document["references"].append(
            {"path": "references/extra.txt", "content": base64.b64encode(b"x").decode()}
        )
    else:
        document["references"].append(document["references"][0])

    with pytest.raises(SkillBundleCodecError, match="missing|undeclared|duplicate"):
        decode_skill_bundle(json.dumps(document, sort_keys=True, separators=(",", ":")).encode())


def test_malformed_utf8_and_oversized_inputs_are_rejected() -> None:
    with pytest.raises(SkillBundleCodecError, match="UTF-8"):
        decode_skill_bundle(b"\xff")
    with pytest.raises(SkillBundleCodecError, match="64 KiB"):
        decode_skill_bundle(b"---\n" + b"x" * (64 * 1024))
    with pytest.raises(SkillBundleCodecError, match="2 MiB"):
        decode_skill_bundle(b"x" * (MAX_ENCODED_SKILL_BUNDLE_BYTES + 1))


def test_reference_total_over_one_mib_is_rejected_before_catalog_install() -> None:
    content = b"x" * (1024 * 1024 + 1)
    document = {
        "kind": "fdai.skill-bundle",
        "markdown": _skill().decode(),
        "references": [
            {
                "content": base64.b64encode(content).decode(),
                "path": "references/large.bin",
            }
        ],
        "version": 1,
    }

    with pytest.raises(SkillBundleCodecError, match="1 MiB"):
        decode_skill_bundle(json.dumps(document, sort_keys=True, separators=(",", ":")).encode())

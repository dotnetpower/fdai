"""Governed skill bundle manifest boundary tests."""

from __future__ import annotations

import json

import pytest

from fdai.core.skills.bundle_manifest import (
    SkillBundleManifestError,
    encode_skill_bundle_manifest,
    parse_skill_bundle_manifest,
)


def _document() -> dict[str, object]:
    return {
        "name": "incident-evidence-pack",
        "version": "1.0.0",
        "description": "Reviewed incident evidence procedures.",
        "source": "publisher.example",
        "members": [
            {"name": "inventory-evidence", "version": "==1.2.3"},
            {"name": "log-evidence", "version": "==2.0.0"},
        ],
        "allowed_agents": ["Bragi"],
        "required_tools": ["query_inventory", "query_log"],
        "instruction": "Use the members in declared order.",
    }


def test_manifest_round_trip_is_canonical_ordered_and_digest_verified() -> None:
    raw = encode_skill_bundle_manifest(_document())

    bundle = parse_skill_bundle_manifest(raw)

    assert bundle.manifest.name == "incident-evidence-pack"
    assert [member.name for member in bundle.manifest.members] == [
        "inventory-evidence",
        "log-evidence",
    ]
    assert bundle.manifest.members[0].exact_version == "1.2.3"
    assert bundle.enabled is False
    assert encode_skill_bundle_manifest(json.loads(raw)) == raw


def test_duplicate_member_and_non_exact_version_are_rejected() -> None:
    duplicate = _document()
    duplicate_members = duplicate["members"]
    assert isinstance(duplicate_members, list)
    duplicate_members.append(duplicate_members[0])
    incompatible = _document()
    incompatible_members = incompatible["members"]
    assert isinstance(incompatible_members, list)
    first = incompatible_members[0]
    assert isinstance(first, dict)
    first["version"] = ">=1.2.3"

    with pytest.raises(SkillBundleManifestError, match="duplicates"):
        parse_skill_bundle_manifest(encode_skill_bundle_manifest(duplicate))
    with pytest.raises(SkillBundleManifestError, match="exact"):
        parse_skill_bundle_manifest(encode_skill_bundle_manifest(incompatible))


def test_oversized_instruction_and_unknown_keys_are_rejected() -> None:
    oversized = _document()
    oversized["instruction"] = "x" * (8 * 1024 + 1)
    unknown = _document()
    unknown["extra"] = True

    with pytest.raises(SkillBundleManifestError, match="8 KiB"):
        parse_skill_bundle_manifest(encode_skill_bundle_manifest(oversized))
    with pytest.raises(SkillBundleManifestError, match="keys mismatch"):
        parse_skill_bundle_manifest(encode_skill_bundle_manifest(unknown))


def test_digest_tamper_duplicate_json_key_and_noncanonical_bytes_fail() -> None:
    raw = encode_skill_bundle_manifest(_document())
    decoded = json.loads(raw)
    decoded["description"] = "changed"
    tampered = json.dumps(decoded, sort_keys=True, separators=(",", ":")).encode()
    duplicate = raw.replace(
        b'{"allowed_agents":',
        b'{"name":"x","name":"y","allowed_agents":',
        1,
    )

    with pytest.raises(SkillBundleManifestError, match="digest mismatch"):
        parse_skill_bundle_manifest(tampered)
    with pytest.raises(SkillBundleManifestError, match="duplicate key"):
        parse_skill_bundle_manifest(duplicate)
    with pytest.raises(SkillBundleManifestError, match="canonical"):
        parse_skill_bundle_manifest(b" " + raw)

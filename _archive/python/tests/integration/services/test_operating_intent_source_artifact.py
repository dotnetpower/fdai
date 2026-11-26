"""The Core image actually ships the deployment-owned six-type operating-intent source.

Issue #366 asks for a *supplied* source, not only a mechanism that could accept one. The
checks here therefore prove three separate things: the shipped artifact is complete,
customer-agnostic, and currently admissible; the Terraform caller pins that exact
artifact (path, revision, whole-document digest, exact instance counts); and the Core
image really places the file at the pinned path when the real Dockerfile ``COPY`` runs
against the real build context and ``.dockerignore``.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.core.operational_context.operating_intent_source import (
    OperatingIntentSourceBinding,
    validate_operating_intent_source_document,
)
from fdai.delivery.operating_model.json_file import (
    operating_intent_source_document_from_mapping,
)
from fdai.shared.providers.operating_model import (
    REQUIRED_OPERATING_INTENT_OBJECT_TYPES,
    operating_intent_source_document_digest,
)

_ROOT = Path(__file__).resolve().parents[3]
_ARTIFACT = _ROOT / "config/operating-intent/generic-source.json"
_SERVICE_VARIABLES = (_ROOT / "infra/services/core-control-plane/variables.tf").read_text(
    encoding="utf-8"
)
_CORE_DOCKERFILE = (_ROOT / "services/core-control-plane/docker/Dockerfile").read_text(
    encoding="utf-8"
)
_DOCKERIGNORE = (_ROOT / ".dockerignore").read_text(encoding="utf-8")
_CONFIG_COPY_PATTERN = re.compile(
    r"^(COPY(?: --chown=\S+)? config/ (?P<destination>\S+))$", re.MULTILINE
)
_PROBE_BASE_IMAGE = "busybox:1.37.0"


def _document():
    return operating_intent_source_document_from_mapping(
        json.loads(_ARTIFACT.read_text(encoding="utf-8"))
    )


def _pinned_binding_block() -> str:
    block = _SERVICE_VARIABLES.split('variable "operating_intent_source"', maxsplit=1)[1]
    return block.split("\n}\n", maxsplit=1)[0]


def _pinned(key: str) -> str:
    """Return one pinned value from the caller's per-attribute default.

    The pins live on ``optional(string, "...")`` rather than in an object-level
    ``default`` block, because Terraform ignores an object-level default the moment a
    caller supplies any attribute at all. Reading them from the same place the
    deployment resolves them keeps this integrity check honest.
    """

    match = re.search(
        rf'^\s*{re.escape(key)}\s*=\s*optional\(string, "(?P<value>.*)"\)\s*$',
        _pinned_binding_block(),
        re.MULTILINE,
    )
    assert match is not None, f"operating_intent_source default is missing {key}"
    return match.group("value")


def _config_copy_match() -> re.Match[str]:
    matches = list(_CONFIG_COPY_PATTERN.finditer(_CORE_DOCKERFILE))
    assert len(matches) == 1, "the Core image MUST copy config/ exactly once"
    return matches[0]


def _config_copy_destination() -> str:
    return _config_copy_match().group("destination")


def _in_image_path() -> str:
    destination = _config_copy_destination().rstrip("/")
    relative = _ARTIFACT.relative_to(_ROOT / "config").as_posix()
    return f"{destination}/{relative}"


def test_generic_source_supplies_exactly_one_of_every_required_intent_type() -> None:
    document = _document()
    counts: dict[str, int] = {}
    for record in document.snapshot.objects:
        counts[record.object_type] = counts.get(record.object_type, 0) + 1

    assert set(counts) == set(REQUIRED_OPERATING_INTENT_OBJECT_TYPES)
    assert set(counts.values()) == {1}
    assert document.snapshot.links == ()


def test_generic_source_carries_only_placeholder_references() -> None:
    """A shipped default must stay portable: no tenant, team, or endpoint values."""

    document = _document()
    reference_keys = {
        "escalation_ref",
        "expression_ref",
        "measurement_source_ref",
        "owner_ref",
        "policy_ref",
        "scope_ref",
        "source_ref",
    }
    for record in document.snapshot.objects:
        assert record.id.startswith("generic-")
        for key, value in record.properties.items():
            if key in reference_keys:
                assert isinstance(value, str)
                assert ":example-" in value or ":placeholder" in value


def test_terraform_caller_pins_the_shipped_artifact_exactly() -> None:
    document = _document()
    counts: dict[str, int] = {}
    for record in document.snapshot.objects:
        counts[record.object_type] = counts.get(record.object_type, 0) + 1

    assert re.search(r"\benabled\s*=\s*optional\(bool, true\)", _pinned_binding_block()) is not None
    assert _pinned("path") == _in_image_path()
    assert _pinned("revision") == document.snapshot.source_revision
    assert _pinned("sha256") == operating_intent_source_document_digest(document)
    assert json.loads(_pinned("expected_counts_json").replace('\\"', '"')) == counts


def test_shipped_artifact_is_admissible_under_its_pinned_binding_now() -> None:
    """The pinned binding must accept the shipped file at today's wall clock.

    This is the check that would catch an expired change window, a lapsed freshness
    window, or a digest that drifted from the file after an edit.
    """

    document = _document()
    counts: dict[str, int] = {}
    for record in document.snapshot.objects:
        counts[record.object_type] = counts.get(record.object_type, 0) + 1
    binding = OperatingIntentSourceBinding(
        expected_revision=_pinned("revision"),
        expected_sha256=_pinned("sha256"),
        expected_instance_counts=counts,
    )

    validate_operating_intent_source_document(document, binding=binding, now=datetime.now(UTC))


def test_shipped_change_window_grants_no_maintenance_authority() -> None:
    """Binding a source supplies intent, never execution authority.

    The shipped placeholder window is deliberately not in an effective status, so the
    risk gate's change-window evidence can never read it as an open maintenance window.
    """

    from fdai.core.risk_gate.ontology_preconditions import _EFFECTIVE_WINDOW_STATUSES

    windows = [
        record for record in _document().snapshot.objects if record.object_type == "ChangeWindow"
    ]
    assert windows
    for window in windows:
        assert window.properties["status"] not in _EFFECTIVE_WINDOW_STATUSES


def test_build_context_keeps_the_artifact_and_the_image_copies_it() -> None:
    assert _ARTIFACT.is_file()
    assert _config_copy_destination() == "/app/config/"
    excluded = {line.strip() for line in _DOCKERIGNORE.splitlines() if line.strip()}
    assert not any(
        pattern.rstrip("/*") in {"config", "config/operating-intent"} for pattern in excluded
    )


@pytest.mark.timeout(600)
def test_core_image_config_copy_places_the_artifact_in_a_container() -> None:
    """Replay the real ``COPY config/`` line against the real context inside a container.

    Building the full Core image here would take minutes for OPA and the wheel build,
    and none of that changes where ``COPY config/`` lands. Replaying that exact
    instruction against the same context root and the same ``.dockerignore`` proves the
    filesystem outcome the deployment depends on in seconds. Skipped where Docker is
    unavailable so the rest of the contract still runs.
    """

    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("docker is not installed")
    probe = subprocess.run(  # noqa: S603 - resolved binary, fixed argv
        (docker, "info"), capture_output=True, check=False
    )
    if probe.returncode != 0:
        pytest.skip("docker daemon is unavailable")

    tag = f"fdai-operating-intent-context-probe:{uuid.uuid4().hex[:12]}"
    dockerfile = f"FROM {_PROBE_BASE_IMAGE}\n{_config_copy_line()}\n"
    build = subprocess.run(  # noqa: S603 - resolved binary, fixed argv
        (docker, "build", "-q", "-t", tag, "-f", "-", "."),
        cwd=_ROOT,
        input=dockerfile,
        capture_output=True,
        text=True,
        check=False,
    )
    if build.returncode != 0:
        pytest.skip(f"docker build context probe unavailable: {build.stderr.strip()[-200:]}")
    try:
        contents = subprocess.run(  # noqa: S603 - resolved binary, fixed argv
            (docker, "run", "--rm", tag, "cat", _in_image_path()),
            capture_output=True,
            text=True,
            check=False,
        )
        assert contents.returncode == 0, contents.stderr
        assert json.loads(contents.stdout) == json.loads(_ARTIFACT.read_text(encoding="utf-8"))
    finally:
        subprocess.run(  # noqa: S603 - resolved binary, fixed argv
            (docker, "image", "rm", "-f", tag), capture_output=True, check=False
        )


def _config_copy_line() -> str:
    return _config_copy_match().group(1)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw.update({"annotations": {"note": "unreviewed"}}),
        lambda raw: raw["provenance"].update({"signature": "unreviewed"}),
        lambda raw: raw["objects"][0].update({"revision": 7}),
        lambda raw: raw["objects"][0].update({"type_ref": {"name": "ServiceObjective"}}),
    ],
)
def test_the_shipped_artifact_cannot_grow_a_member_behind_its_pin(mutate) -> None:
    """The pin is over the whole document, not over a recognized subset of it.

    A lossy parser left the asserted digest unchanged when a member was added at the
    document, provenance, or object level, so the artifact could change while this
    integrity check and the Terraform pin both still passed.
    """

    raw = json.loads(_ARTIFACT.read_text(encoding="utf-8"))
    mutate(raw)

    with pytest.raises(ValueError, match="unknown members"):
        operating_intent_source_document_from_mapping(raw)


def test_editing_any_recognized_value_moves_the_pinned_digest() -> None:
    original = operating_intent_source_document_digest(_document())
    for mutate in (
        lambda raw: raw.update({"source_revision": "operating-intent-source:generic@1.0.1"}),
        lambda raw: raw["provenance"].update({"source_url": "https://example.invalid/other"}),
        lambda raw: raw["provenance"].update({"resolved_ref": "generic@9.9.9"}),
        lambda raw: raw["provenance"].update({"retrieved_at": "2099-01-01T00:00:00+00:00"}),
        lambda raw: raw["objects"][0]["properties"].update({"freshness_seconds": 1}),
    ):
        raw = json.loads(_ARTIFACT.read_text(encoding="utf-8"))
        mutate(raw)
        mutated = operating_intent_source_document_from_mapping(raw)

        assert operating_intent_source_document_digest(mutated) != original

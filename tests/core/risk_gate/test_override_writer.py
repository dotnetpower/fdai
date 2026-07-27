"""Wave M1.4 - governance.override-ceiling Rego overlay writer."""

from __future__ import annotations

import re

import pytest

from fdai.core.risk_gate.override_writer import (
    Axis,
    OverrideRequest,
    OverrideWriterError,
    Scope,
    TargetLevel,
    render_override_rego,
)


def _valid_request(**overrides: object) -> OverrideRequest:
    base = dict(
        override_id="ovr-001",
        action_type_id="ops.scale-out",
        axis=Axis.CEILING,
        target_level=TargetLevel.ENFORCE_HIL,
        scope=Scope.RESOURCE,
        scope_ref="rg/fdai/vm-a",
        expires_at="2026-12-31T00:00:00Z",
        justification="prod nightly outage - reduce autonomy for one week.",
        requester_id="user-alpha",
        approver_id="user-beta",
    )
    base.update(overrides)
    return OverrideRequest(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_render_writes_metadata_and_rego_document() -> None:
    overlay = render_override_rego(_valid_request())
    assert overlay.path == "policies/action_types/ops.scale-out/ovr-001.rego"
    content = overlay.content
    # Metadata block front-matter.
    assert content.startswith("# METADATA")
    # Package name uses only [a-z0-9_] segments.
    m = re.search(r"^package (fdai\.action_types\.[a-z0-9_.]+)$", content, re.MULTILINE)
    assert m is not None
    package = m.group(1)
    assert package == "fdai.action_types.ops_scale_out.ovr_001"
    # Applicability guard.
    assert 'input.action_type == "ops.scale-out"' in content
    assert 'input.scope.kind == "resource"' in content
    assert 'input.scope.ref == "rg/fdai/vm-a"' in content
    assert 'input.now <= "2026-12-31T00:00:00Z"' in content
    # Verdict block carries the enum values verbatim.
    assert '"axis": "ceiling"' in content
    assert '"level": "enforce_hil"' in content
    assert '"override_id": "ovr-001"' in content


def test_shadow_only_target_level_renders() -> None:
    overlay = render_override_rego(_valid_request(target_level=TargetLevel.SHADOW_ONLY))
    assert '"level": "shadow_only"' in overlay.content


def test_resource_group_scope_renders() -> None:
    overlay = render_override_rego(_valid_request(scope=Scope.RESOURCE_GROUP))
    assert 'input.scope.kind == "resource-group"' in overlay.content


def test_all_five_axes_render() -> None:
    for axis in Axis:
        overlay = render_override_rego(_valid_request(axis=axis))
        assert f'"axis": "{axis.value}"' in overlay.content


# ---------------------------------------------------------------------------
# Invariants (fail-closed)
# ---------------------------------------------------------------------------


def test_empty_override_id_rejected() -> None:
    with pytest.raises(OverrideWriterError, match="override_id"):
        render_override_rego(_valid_request(override_id=""))


def test_empty_action_type_id_rejected() -> None:
    with pytest.raises(OverrideWriterError, match="action_type_id MUST be non-empty"):
        render_override_rego(_valid_request(action_type_id=""))


def test_action_type_id_pattern_enforced() -> None:
    with pytest.raises(OverrideWriterError, match="MUST match"):
        render_override_rego(_valid_request(action_type_id="1-bad-start"))


def test_action_type_id_length_enforced() -> None:
    with pytest.raises(OverrideWriterError, match="at most"):
        render_override_rego(_valid_request(action_type_id="a" * 81))


def test_self_approval_rejected() -> None:
    with pytest.raises(OverrideWriterError, match="self-approval"):
        render_override_rego(_valid_request(requester_id="me", approver_id="me"))


def test_short_justification_rejected() -> None:
    with pytest.raises(OverrideWriterError, match="at least 20"):
        render_override_rego(_valid_request(justification="short"))


def test_long_justification_rejected() -> None:
    with pytest.raises(OverrideWriterError, match="at most 500"):
        render_override_rego(_valid_request(justification="x" * 501))


def test_empty_scope_ref_rejected() -> None:
    with pytest.raises(OverrideWriterError, match="scope_ref"):
        render_override_rego(_valid_request(scope_ref="   "))


def test_missing_expires_at_rejected() -> None:
    with pytest.raises(OverrideWriterError, match="expires_at MUST be non-empty"):
        render_override_rego(_valid_request(expires_at=""))


def test_bad_iso_expiry_rejected() -> None:
    with pytest.raises(OverrideWriterError, match="ISO-8601"):
        render_override_rego(_valid_request(expires_at="not-a-timestamp"))


def test_missing_requester_or_approver_rejected() -> None:
    with pytest.raises(OverrideWriterError, match="requester_id"):
        render_override_rego(_valid_request(requester_id=""))
    with pytest.raises(OverrideWriterError, match="approver_id"):
        render_override_rego(_valid_request(approver_id=""))


# ---------------------------------------------------------------------------
# Escaping
# ---------------------------------------------------------------------------


def test_scope_ref_double_quote_is_escaped_in_rego_string() -> None:
    overlay = render_override_rego(_valid_request(scope_ref='rg/"with-quote"/vm'))
    assert r'input.scope.ref == "rg/\"with-quote\"/vm"' in overlay.content


def test_scope_ref_backslash_is_escaped() -> None:
    overlay = render_override_rego(_valid_request(scope_ref="rg\\ns\\vm"))
    assert r'input.scope.ref == "rg\\ns\\vm"' in overlay.content


def test_justification_newlines_collapse_in_metadata_comment() -> None:
    overlay = render_override_rego(
        _valid_request(justification="line one\nline two - twenty chars long")
    )
    # No bare newlines inside a comment line.
    comment_lines = [ln for ln in overlay.content.splitlines() if ln.startswith("#")]
    for ln in comment_lines:
        assert "\r" not in ln


# ---------------------------------------------------------------------------
# Filesystem safety
# ---------------------------------------------------------------------------


def test_path_traversal_in_override_id_rejected() -> None:
    with pytest.raises(OverrideWriterError, match="MUST match"):
        render_override_rego(_valid_request(override_id="../evil"))


def test_slashes_in_override_id_are_rejected_rather_than_sanitised() -> None:
    """The id is a filename, a Rego package segment, and a string literal.
    Rewriting a separator into something safe leaves the caller believing an id
    they never supplied; refusing it keeps the written path the one requested.
    """
    with pytest.raises(OverrideWriterError, match="MUST match"):
        render_override_rego(_valid_request(override_id="a/b/c"))


def test_an_override_id_cannot_become_rego_syntax() -> None:
    """The id is interpolated into a Rego string literal. A quote ends that
    literal and everything after it is parsed as policy, so a request could
    rewrite the verdict it was supposed to describe.
    """
    with pytest.raises(OverrideWriterError, match="MUST match"):
        render_override_rego(_valid_request(override_id='ovr-1", "level": "autonomous'))


def test_an_override_id_cannot_define_a_new_rule() -> None:
    """A newline escapes the literal entirely. This exact input rendered a
    working `allow := true` into a ceiling overlay whose whole purpose is that
    it can only narrow autonomy.
    """
    with pytest.raises(OverrideWriterError, match="MUST match"):
        render_override_rego(_valid_request(override_id='ovr-1"\n}\nallow := true\nx := {"y": "'))


@pytest.mark.parametrize("field", ["requester_id", "approver_id"])
def test_an_identity_cannot_escape_the_metadata_comment(field: str) -> None:
    """Identities are rendered as `# key: value` comments. A newline ends the
    comment and the next line is policy.
    """
    with pytest.raises(OverrideWriterError, match="line break"):
        render_override_rego(_valid_request(**{field: "alice\nallow := true\n# x"}))


def test_a_unicode_lookalike_cannot_stand_in_for_an_action_type() -> None:
    """str.isalnum() accepts every Unicode letter, so a Cyrillic 'с' passed as
    an ASCII 'c' and named a different action type than a reviewer read.
    """
    with pytest.raises(OverrideWriterError, match="MUST match"):
        render_override_rego(_valid_request(action_type_id="ops.restart-servi\u0441e"))


def test_a_legitimate_override_still_renders_one_verdict() -> None:
    overlay = render_override_rego(_valid_request(override_id="ovr-2026-001"))

    assert '"override_id": "ovr-2026-001",' in overlay.content
    assert [line for line in overlay.content.splitlines() if line.startswith("allow")] == []
    assert overlay.content.count('"level":') == 1

"""Tests for :class:`RegoParser`.

Exercises the four required behaviors:

- happy path: a module with a valid ``# METADATA`` block lifts
  ``custom.resource_type`` and synthesizes id + check_logic.
- fallback: a module WITHOUT METADATA falls back to inferred metadata
  (id from the package path, ``resource_type: unknown``).
- recursive tree walk: modules discovered under nested subdirectories
  keep their subpath in the ``check_logic.reference`` and ``origin``.
- fail-closed: a module without a package declaration, and a module
  with a malformed METADATA block, both raise :class:`ParseError`.

Every fixture lives in ``tmp_path`` (no vendored .rego committed) so
the test suite stays hermetic and customer-agnostic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aiopspilot.rule_catalog.pipeline.parse import (
    ParseError,
    ParserName,
    RegoParser,
    build_parser,
)

# ---------------------------------------------------------------------------
# Fixture Rego modules — kept as string constants so the test file stays
# a single self-contained source of truth for every shape under test.
# ---------------------------------------------------------------------------

_MODULE_WITH_METADATA = """\
# METADATA
# title: Deny privileged containers
# description: Reject pods that request privileged mode.
# custom:
#   resource_type: kubernetes-cluster
#   severity: high
package k8s.gatekeeper.psp.privileged

violation[{"msg": msg}] {
    input.review.object.spec.containers[_].securityContext.privileged
    msg := "privileged containers are forbidden"
}
"""

_MODULE_WITHOUT_METADATA = """\
package k8s.gatekeeper.rbac.no_wildcard

violation[{"msg": msg}] {
    input.review.object.rules[_].verbs[_] == "*"
    msg := "wildcard verbs are forbidden"
}
"""

_MODULE_MISSING_PACKAGE = """\
# METADATA
# title: no package here
violation[{"msg": "oops"}] { true }
"""

_MODULE_MALFORMED_METADATA = """\
# METADATA
# title: broken
#   custom: [not, a, mapping]
package k8s.gatekeeper.broken
"""


def _write(tree_root: Path, subpath: str, body: str) -> Path:
    target = tree_root / subpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# Dispatcher wiring
# ---------------------------------------------------------------------------


def test_build_parser_rego_returns_regoparser() -> None:
    parser = build_parser(ParserName.REGO)
    assert isinstance(parser, RegoParser)
    assert parser.name is ParserName.REGO


def test_build_parser_accepts_string_name_rego() -> None:
    parser = build_parser("rego")
    assert isinstance(parser, RegoParser)


# ---------------------------------------------------------------------------
# Happy path — METADATA present, custom.resource_type lifted
# ---------------------------------------------------------------------------


def test_rego_parser_happy_path_with_metadata(tmp_path: Path) -> None:
    _write(tmp_path, "psp.rego", _MODULE_WITH_METADATA)

    report = RegoParser().parse(tmp_path)

    assert report.parser is ParserName.REGO
    assert report.rule_count == 1
    parsed = report.rules[0]
    assert parsed.origin == "psp.rego"
    assert parsed.raw["id"] == "k8s.gatekeeper.psp.privileged"
    assert parsed.raw["resource_type"] == "kubernetes-cluster"
    assert parsed.raw["check_logic"] == {
        "kind": "rego",
        "reference": "policies/vendored/psp.rego",
    }


# ---------------------------------------------------------------------------
# Fallback — METADATA absent, resource_type defaults to "unknown"
# ---------------------------------------------------------------------------


def test_rego_parser_fallback_without_metadata(tmp_path: Path) -> None:
    _write(tmp_path, "rbac.rego", _MODULE_WITHOUT_METADATA)

    report = RegoParser().parse(tmp_path)

    assert report.rule_count == 1
    parsed = report.rules[0]
    assert parsed.raw["id"] == "k8s.gatekeeper.rbac.no_wildcard"
    assert parsed.raw["resource_type"] == "unknown"
    assert parsed.raw["check_logic"]["reference"] == "policies/vendored/rbac.rego"


def test_rego_parser_fallback_when_custom_field_missing(tmp_path: Path) -> None:
    body = "# METADATA\n# title: has title but no custom block\npackage k8s.gatekeeper.no_custom\n"
    _write(tmp_path, "no_custom.rego", body)

    report = RegoParser().parse(tmp_path)

    assert report.rule_count == 1
    assert report.rules[0].raw["resource_type"] == "unknown"


def test_rego_parser_fallback_when_resource_type_wrong_type(tmp_path: Path) -> None:
    body = "# METADATA\n# custom:\n#   resource_type: 42\npackage k8s.gatekeeper.numeric_rt\n"
    _write(tmp_path, "numeric_rt.rego", body)

    report = RegoParser().parse(tmp_path)

    assert report.rule_count == 1
    assert report.rules[0].raw["resource_type"] == "unknown"


# ---------------------------------------------------------------------------
# Recursive walk — subpaths preserved in origin + reference
# ---------------------------------------------------------------------------


def test_rego_parser_walks_tree_recursively(tmp_path: Path) -> None:
    _write(tmp_path, "top.rego", _MODULE_WITH_METADATA)
    _write(tmp_path, "library/psp/privileged.rego", _MODULE_WITH_METADATA)
    _write(
        tmp_path,
        "library/rbac/no_wildcard.rego",
        _MODULE_WITHOUT_METADATA,
    )
    # Non-.rego siblings MUST be ignored.
    (tmp_path / "library" / "README.md").write_text("noise\n", encoding="utf-8")

    report = RegoParser().parse(tmp_path)

    # Deterministic lexicographic order across platforms.
    assert [r.origin for r in report.rules] == [
        "library/psp/privileged.rego",
        "library/rbac/no_wildcard.rego",
        "top.rego",
    ]
    # The nested rule's reference preserves its subpath under
    # policies/vendored/, so the loader-side resolver finds it inside
    # the vendored snapshot for this source.
    nested = next(r for r in report.rules if r.origin == "library/psp/privileged.rego")
    assert nested.raw["check_logic"]["reference"] == (
        "policies/vendored/library/psp/privileged.rego"
    )


def test_rego_parser_is_deterministic(tmp_path: Path) -> None:
    _write(tmp_path, "b.rego", _MODULE_WITHOUT_METADATA)
    _write(
        tmp_path,
        "a.rego",
        "package a.pkg\n",
    )

    first = RegoParser().parse(tmp_path)
    second = RegoParser().parse(tmp_path)

    assert [r.origin for r in first.rules] == ["a.rego", "b.rego"]
    assert [r.origin for r in first.rules] == [r.origin for r in second.rules]


# ---------------------------------------------------------------------------
# Fail-closed — structural failures
# ---------------------------------------------------------------------------


def test_rego_parser_rejects_non_directory(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    with pytest.raises(ParseError, match="MUST be a directory"):
        RegoParser().parse(missing)


def test_rego_parser_fails_on_missing_package(tmp_path: Path) -> None:
    _write(tmp_path, "no_package.rego", _MODULE_MISSING_PACKAGE)

    with pytest.raises(ParseError, match="missing package declaration"):
        RegoParser().parse(tmp_path)


def test_rego_parser_fails_on_malformed_metadata_yaml(tmp_path: Path) -> None:
    body = (
        "# METADATA\n# custom:\n#   - resource_type: [unbalanced\npackage k8s.gatekeeper.badyaml\n"
    )
    _write(tmp_path, "bad.rego", body)

    with pytest.raises(ParseError, match="bad.rego"):
        RegoParser().parse(tmp_path)


def test_rego_parser_fails_on_non_mapping_metadata(tmp_path: Path) -> None:
    body = "# METADATA\n# - one\n# - two\npackage k8s.gatekeeper.sequence_meta\n"
    _write(tmp_path, "seq.rego", body)

    with pytest.raises(ParseError, match="METADATA body must be a YAML mapping"):
        RegoParser().parse(tmp_path)


def test_rego_parser_fails_on_empty_metadata_block(tmp_path: Path) -> None:
    body = "# METADATA\npackage k8s.gatekeeper.empty_meta\n"
    _write(tmp_path, "empty.rego", body)

    with pytest.raises(ParseError, match="METADATA block is empty"):
        RegoParser().parse(tmp_path)


def test_rego_parser_reports_multiple_errors_with_preview(tmp_path: Path) -> None:
    # Ensure the aggregated error message truncates cleanly.
    for idx in range(7):
        _write(tmp_path, f"broken_{idx}.rego", _MODULE_MISSING_PACKAGE)

    with pytest.raises(ParseError) as excinfo:
        RegoParser().parse(tmp_path)
    message = str(excinfo.value)
    # First five appear inline; the remainder collapses to a counter.
    assert "broken_0.rego" in message
    assert "(+2 more)" in message


# ---------------------------------------------------------------------------
# Malformed structure — the malformed METADATA fixture must fail cleanly
# without ever emitting a partial ParsedRule.
# ---------------------------------------------------------------------------


def test_rego_parser_malformed_metadata_never_leaks_partial_rule(tmp_path: Path) -> None:
    _write(tmp_path, "broken.rego", _MODULE_MALFORMED_METADATA)

    with pytest.raises(ParseError):
        RegoParser().parse(tmp_path)


def test_rego_parser_empty_tree_returns_empty_report(tmp_path: Path) -> None:
    # No .rego files → empty ParseReport (not an error).
    report = RegoParser().parse(tmp_path)
    assert report.parser is ParserName.REGO
    assert report.rule_count == 0


# ---------------------------------------------------------------------------
# LocalDirectoryFetcher-style fixture — proves the parser is drop-in
# compatible with a fetcher that vendors an OSS Rego source into the
# snapshot tree. Deliberately no network / no git.
# ---------------------------------------------------------------------------


def test_rego_parser_ingests_vendored_gatekeeper_style_snapshot(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    _write(tree, "library/psp/privileged.rego", _MODULE_WITH_METADATA)
    _write(tree, "library/rbac/no_wildcard.rego", _MODULE_WITHOUT_METADATA)

    report = RegoParser().parse(tree)

    assert report.rule_count == 2
    ids = {r.raw["id"] for r in report.rules}
    assert ids == {
        "k8s.gatekeeper.psp.privileged",
        "k8s.gatekeeper.rbac.no_wildcard",
    }
    for parsed in report.rules:
        assert parsed.raw["check_logic"]["kind"] == "rego"
        assert parsed.raw["check_logic"]["reference"].startswith("policies/vendored/library/")

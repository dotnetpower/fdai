"""Synthetic private configuration fixtures; no provider or authority is exercised."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

import pytest
from fdai.runtime.alert_noise_config import (
    MAX_CONFIG_BINDINGS,
    MAX_CONFIG_BYTES,
    PRINCIPAL_SCOPES_ENV,
    SCOPE_BINDINGS_ENV,
    SOURCE_REVISION_ENV,
    WRITER_BINDINGS_ENV,
    alert_requester_ref,
    parse_alert_noise_config,
)

_SUBJECT = str(UUID(int=1))
_EXECUTOR = str(UUID(int=2))


def _requester(subject: str, scope: str) -> str:
    raw = json.dumps(["operator-alert-quality-v1", subject, scope], separators=(",", ":"))
    return "principal:" + hashlib.sha256(raw.encode()).hexdigest()


def _environment(
    *,
    writers: bool = True,
    source: bool = True,
    scope_count: int = 1,
) -> dict[str, str]:
    """Use only generated placeholder OIDs and explicit test-only commit identities."""
    scopes = [
        {
            "subscription_id": str(UUID(int=10)),
            "resource_group": f"example-{index}",
            "tenant_ref": "tenant:example",
            "scope_ref": f"scope:example-{index}",
        }
        for index in range(scope_count)
    ]
    result = {
        SCOPE_BINDINGS_ENV: json.dumps(scopes),
        PRINCIPAL_SCOPES_ENV: json.dumps({_SUBJECT: [scope["scope_ref"] for scope in scopes]}),
    }
    if source:
        result[SOURCE_REVISION_ENV] = "a" * 40
    if writers:
        result[WRITER_BINDINGS_ENV] = json.dumps(
            [
                {
                    "scope_ref": scope["scope_ref"],
                    "executor_ref": _requester(_EXECUTOR, scope["scope_ref"]),
                    "repository_ref": "repository:example",
                    "repository_revision": "commit:" + "b" * 40,
                    "verification_trust_anchor_id": "verification:test-only",
                    "principal_refs": {
                        subject: _requester(subject, scope["scope_ref"])
                        for subject in (_SUBJECT, _EXECUTOR, str(UUID(int=3)), str(UUID(int=4)))
                    },
                }
                for scope in scopes
            ]
        )
    return result


def test_absent_configuration_preserves_none_and_ignores_unrelated_revision() -> None:
    assert parse_alert_noise_config({}) is None
    assert parse_alert_noise_config({SOURCE_REVISION_ENV: "not-an-alert-opt-in"}) is None


def test_missing_source_remains_none_without_erasing_valid_bindings() -> None:
    config = parse_alert_noise_config(_environment(source=False))
    assert config is not None and config.source_revision is None
    assert tuple(config.scopes) == tuple(config.writers) == ("scope:example-0",)


def test_private_maps_use_exact_operator_identity_and_no_approval_fields() -> None:
    config = parse_alert_noise_config(_environment(scope_count=2))
    assert config is not None and config.source_revision == "commit:" + "a" * 40
    expected = {_requester(_SUBJECT, f"scope:example-{index}"): _SUBJECT for index in range(2)}
    assert config.requester_subjects == expected
    assert config.principal_scopes[_SUBJECT] == frozenset(config.scopes)
    writer = config.writers["scope:example-0"]
    assert writer.principal_refs[_SUBJECT] == _requester(_SUBJECT, writer.scope_ref)
    assert writer.executor_ref == writer.principal_refs[_EXECUTOR]
    assert writer.repository_revision == "commit:" + "b" * 40
    assert _SUBJECT not in repr(config) + repr(writer) + repr(config.scopes[writer.scope_ref])
    with pytest.raises(TypeError):
        config.requester_subjects["principal:other"] = _SUBJECT  # type: ignore[index]


def test_requester_reference_matches_json_bytes_and_scope_is_not_normalized() -> None:
    assert alert_requester_ref(_SUBJECT, "scope:example-0") == _requester(
        _SUBJECT, "scope:example-0"
    )
    assert alert_requester_ref(_SUBJECT, "scope:example-0") != alert_requester_ref(
        _SUBJECT, "scope:example-1"
    )
    with pytest.raises(ValueError):
        alert_requester_ref(_SUBJECT, "scope:example-0\n")


@pytest.mark.parametrize("missing", [SCOPE_BINDINGS_ENV, PRINCIPAL_SCOPES_ENV])
def test_explicit_partial_configuration_is_not_absence(missing: str) -> None:
    environment = _environment()
    del environment[missing]
    with pytest.raises(ValueError, match="requires both"):
        parse_alert_noise_config(environment)


@pytest.mark.parametrize("name", [SCOPE_BINDINGS_ENV, PRINCIPAL_SCOPES_ENV, WRITER_BINDINGS_ENV])
@pytest.mark.parametrize("raw", ["", " ", "null", "true", "NaN", "[]", '"private"'])
def test_explicit_empty_or_wrong_shape_is_rejected(name: str, raw: str) -> None:
    environment = _environment()
    environment[name] = raw
    with pytest.raises(ValueError):
        parse_alert_noise_config(environment)


def test_empty_principal_access_is_explicit_denial_not_a_fake_subject() -> None:
    environment = _environment(writers=False)
    for mapping in ({}, {_SUBJECT: []}):
        environment[PRINCIPAL_SCOPES_ENV] = json.dumps(mapping)
        config = parse_alert_noise_config(environment)
        assert config is not None and config.requester_subjects == {} and config.writers == {}


@pytest.mark.parametrize("name", [SCOPE_BINDINGS_ENV, PRINCIPAL_SCOPES_ENV, WRITER_BINDINGS_ENV])
def test_each_document_has_a_strict_byte_bound(name: str) -> None:
    environment = _environment()
    environment[name] = " " * (MAX_CONFIG_BYTES + 1)
    with pytest.raises(ValueError, match="bounded JSON"):
        parse_alert_noise_config(environment)


def test_duplicate_json_keys_including_nested_private_maps_fail_closed() -> None:
    environment = _environment()
    scope_duplicate = environment[SCOPE_BINDINGS_ENV].replace(
        '"scope_ref": "scope:example-0"',
        '"scope_ref": "scope:example-0", "scope_ref": "scope:example-1"',
    )
    ref = _requester(_SUBJECT, "scope:example-0")
    writer_duplicate = environment[WRITER_BINDINGS_ENV].replace(
        f'"{_SUBJECT}": "{ref}"',
        f'"{_SUBJECT}": "{ref}", "{_SUBJECT}": "{ref}"',
    )
    principal_duplicate = '{"' + _SUBJECT + '": [], "' + _SUBJECT + '": []}'
    for name, raw in (
        (SCOPE_BINDINGS_ENV, scope_duplicate),
        (WRITER_BINDINGS_ENV, writer_duplicate),
        (PRINCIPAL_SCOPES_ENV, principal_duplicate),
    ):
        with pytest.raises(ValueError, match="unique object fields") as failure:
            parse_alert_noise_config({**environment, name: raw})
        assert _SUBJECT not in str(failure.value) and ref not in str(failure.value)


def test_scope_and_subject_arrays_are_bounded_without_truncation() -> None:
    config = parse_alert_noise_config(_environment(writers=False, scope_count=MAX_CONFIG_BINDINGS))
    assert config is not None and len(config.scopes) == len(config.requester_subjects) == 64
    with pytest.raises(ValueError, match="bounded array"):
        parse_alert_noise_config(_environment(writers=False, scope_count=MAX_CONFIG_BINDINGS + 1))
    environment = _environment(writers=False)
    environment[PRINCIPAL_SCOPES_ENV] = json.dumps(
        {str(UUID(int=index + 1)): ["scope:example-0"] for index in range(1000)}
    )
    population = parse_alert_noise_config(environment)
    assert population is not None and len(population.requester_subjects) == 1000
    environment[PRINCIPAL_SCOPES_ENV] = json.dumps(
        {str(UUID(int=index + 1)): ["scope:example-0"] for index in range(1001)}
    )
    with pytest.raises(ValueError, match="excessive fields"):
        parse_alert_noise_config(environment)


@pytest.mark.parametrize(
    "subject", ["Thor", "", "person:example", str(UUID(int=0)), str(UUID(int=1)) + "\n"]
)
def test_requesters_must_be_actual_canonical_oid_shapes(subject: str) -> None:
    environment = _environment(writers=False)
    environment[PRINCIPAL_SCOPES_ENV] = json.dumps({subject: ["scope:example-0"]})
    with pytest.raises(ValueError, match="canonical nonzero UUID"):
        parse_alert_noise_config(environment)


@pytest.mark.parametrize("scopes", [["scope:other"], ["scope:example-0"] * 2, [True], ["*"]])
def test_principal_routes_are_exact_unique_and_bound(scopes: list[object]) -> None:
    environment = _environment(writers=False)
    environment[PRINCIPAL_SCOPES_ENV] = json.dumps({_SUBJECT: scopes})
    with pytest.raises(ValueError):
        parse_alert_noise_config(environment)


def test_native_aliases_and_conflicting_tenants_are_rejected() -> None:
    environment = _environment(writers=False, scope_count=2)
    rows = json.loads(environment[SCOPE_BINDINGS_ENV])
    for changes in (
        {"scope_ref": "scope:example-0"},
        {"resource_group": "EXAMPLE-0"},
        {"tenant_ref": "tenant:other"},
    ):
        raw = json.dumps([rows[0], {**rows[1], **changes}])
        with pytest.raises(ValueError, match="duplicate or conflicting"):
            parse_alert_noise_config({**environment, SCOPE_BINDINGS_ENV: raw})


@pytest.mark.parametrize("name", [SCOPE_BINDINGS_ENV, WRITER_BINDINGS_ENV])
def test_unknown_and_missing_fields_do_not_silently_select_a_fallback(name: str) -> None:
    environment = _environment()
    row = json.loads(environment[name])[0]
    for changed in (
        {**row, "authority": True},
        {key: value for key, value in row.items() if key != "scope_ref"},
    ):
        with pytest.raises(ValueError, match="missing, unknown or excessive"):
            parse_alert_noise_config({**environment, name: json.dumps([changed])})


def test_writer_maps_do_not_alias_principals_or_rebind_requesters() -> None:
    environment = _environment()
    row = json.loads(environment[WRITER_BINDINGS_ENV])[0]
    for identities in (
        {},
        {**row["principal_refs"], _SUBJECT: "principal:" + "c" * 64},
        {**row["principal_refs"], _EXECUTOR: row["principal_refs"][_SUBJECT]},
        {"Thor": row["executor_ref"]},
    ):
        with pytest.raises(ValueError):
            parse_alert_noise_config(
                {
                    **environment,
                    WRITER_BINDINGS_ENV: json.dumps(
                        [
                            {**row, "principal_refs": identities},
                        ]
                    ),
                }
            )


@pytest.mark.parametrize(
    "revision", ["", "latest", "a" * 39, "A" * 40, "a" * 40 + "\n", "0" * 40, "commit:" + "0" * 64]
)
def test_source_never_uses_a_synthetic_or_ambiguous_revision(revision: str) -> None:
    environment = _environment()
    with pytest.raises(ValueError, match="explicit nonzero Git commit"):
        parse_alert_noise_config({**environment, SOURCE_REVISION_ENV: revision})
    row = json.loads(environment[WRITER_BINDINGS_ENV])[0]
    with pytest.raises(ValueError, match="explicit nonzero Git commit"):
        parse_alert_noise_config(
            {
                **environment,
                WRITER_BINDINGS_ENV: json.dumps(
                    [
                        {**row, "repository_revision": revision},
                    ]
                ),
            }
        )


@pytest.mark.parametrize("revision", ["a" * 40, "commit:" + "a" * 40, "a" * 64])
def test_exact_commit_shapes_are_preserved_without_artifact_lookup(revision: str) -> None:
    config = parse_alert_noise_config({**_environment(), SOURCE_REVISION_ENV: revision})
    assert config is not None
    assert config.source_revision == "commit:" + revision.removeprefix("commit:")

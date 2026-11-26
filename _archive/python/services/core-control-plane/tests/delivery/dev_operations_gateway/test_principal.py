from __future__ import annotations

import base64
import json

import pytest
from delivery.dev_operations_gateway.principal import (
    PrincipalHeaderError,
    parse_easy_auth_principal,
)


def _encoded(claims: list[object]) -> str:
    payload = json.dumps({"claims": claims}, separators=(",", ":")).encode()
    return base64.b64encode(payload).decode()


def test_easy_auth_principal_accepts_only_bounded_string_claims() -> None:
    principal = parse_easy_auth_principal(
        _encoded(
            [
                {"typ": "oid", "val": "principal-user"},
                {"typ": "groups", "val": "group-contributor"},
                {"typ": "roles", "val": "Contributor"},
            ]
        )
    )
    assert principal.object_id == "principal-user"
    assert principal.groups == frozenset({"group-contributor"})
    assert principal.roles == frozenset({"Contributor"})


@pytest.mark.parametrize(
    "encoded",
    [
        "not-base64%%%",
        _encoded([{"typ": "oid", "val": 12345}]),
        _encoded([{"typ": "oid", "val": "principal-user"}, {"typ": "groups", "val": {}}]),
        _encoded(
            [
                {"typ": "oid", "val": "principal-one"},
                {"typ": "oid", "val": "principal-two"},
            ]
        ),
    ],
)
def test_easy_auth_principal_rejects_malformed_security_claims(encoded: str) -> None:
    with pytest.raises(PrincipalHeaderError):
        parse_easy_auth_principal(encoded)

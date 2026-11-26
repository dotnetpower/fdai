"""Regressions for the optional MySQL and Azure OpenAI substrate bindings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fdai.delivery.chaos.substrate_bindings import (
    aoai_bindings,
    mysql_bindings,
    optional_substrate_bindings,
)

_SUB = "00000000-0000-0000-0000-000000000000"
_RG = "rg-test"
_AOAI_ID = (
    f"/subscriptions/{_SUB}/resourceGroups/{_RG}"
    "/providers/Microsoft.CognitiveServices/accounts/oai-test"
)


def _mysql_env(password_file: Path) -> dict[str, str]:
    return {
        "FDAI_ENFORCE_MYSQL_HOST": "mysql.example.invalid",
        "FDAI_ENFORCE_MYSQL_USER": "labadmin",
        "FDAI_ENFORCE_MYSQL_SERVER": "mysql-test",
        "FDAI_ENFORCE_MYSQL_PW_FILE": str(password_file),
    }


def _aoai_env() -> dict[str, str]:
    return {
        "FDAI_ENFORCE_AOAI_ENDPOINT": "https://oai-test.openai.azure.com/",
        "FDAI_ENFORCE_AOAI_DEPLOYMENT": "chat",
        "FDAI_ENFORCE_AOAI_RESOURCE_ID": _AOAI_ID,
    }


def test_mysql_binding_builds_the_canonical_server_identity(tmp_path: Path) -> None:
    bindings = mysql_bindings(_mysql_env(tmp_path / "pw"), sub_id=_SUB, resource_group=_RG)

    assert bindings["mysql_server_resource_id"] == (
        f"/subscriptions/{_SUB}/resourceGroups/{_RG}"
        "/providers/Microsoft.DBforMySQL/flexibleServers/mysql-test"
    )
    assert callable(bindings["mysql_connect_factory"])


def test_mysql_password_never_enters_the_context(tmp_path: Path) -> None:
    password_file = tmp_path / "pw"
    password_file.write_text("super-secret-value\n", encoding="utf-8")

    bindings = mysql_bindings(_mysql_env(password_file), sub_id=_SUB, resource_group=_RG)

    assert "super-secret-value" not in repr(sorted(bindings))
    assert not any("password" in key for key in bindings)


def test_an_incomplete_mysql_group_stays_unbound(tmp_path: Path) -> None:
    complete = _mysql_env(tmp_path / "pw")

    for omitted in complete:
        partial = {key: value for key, value in complete.items() if key != omitted}
        assert mysql_bindings(partial, sub_id=_SUB, resource_group=_RG) == {}

    blank = {**complete, "FDAI_ENFORCE_MYSQL_SERVER": "   "}
    assert mysql_bindings(blank, sub_id=_SUB, resource_group=_RG) == {}


def test_aoai_binding_uses_the_exact_reported_resource_id() -> None:
    calls: list[str] = []

    def _token() -> str:
        calls.append("token")
        return "token-value"

    bindings = aoai_bindings(_aoai_env(), token_provider=_token)

    assert bindings["aoai_resource_id"] == _AOAI_ID
    assert callable(bindings["aoai_load_request_fn"])
    assert bindings["aoai_load_request_fn"] is not bindings["aoai_probe_request_fn"]
    assert calls == []


def test_an_incomplete_aoai_group_stays_unbound() -> None:
    complete = _aoai_env()

    for omitted in complete:
        partial = {key: value for key, value in complete.items() if key != omitted}
        assert aoai_bindings(partial, token_provider=lambda: "t") == {}


def test_optional_bindings_are_independent(tmp_path: Path) -> None:
    only_mysql: dict[str, Any] = optional_substrate_bindings(
        _mysql_env(tmp_path / "pw"), sub_id=_SUB, resource_group=_RG
    )

    assert "mysql_server_resource_id" in only_mysql
    assert "aoai_resource_id" not in only_mysql
    assert optional_substrate_bindings({}, sub_id=_SUB, resource_group=_RG) == {}

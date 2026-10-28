from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fdai_operator_service.actor_display import ActorDisplayResolver
from fdai_operator_service.families.iam.contracts import DirectoryIdentity

_OID = str(uuid.UUID(int=1))
_OTHER = str(uuid.UUID(int=2))


class _Directory:
    def __init__(self, identities: dict[str, DirectoryIdentity | Exception]) -> None:
        self._identities = identities
        self.calls: list[str] = []

    async def get_by_subject_id(self, subject_id: str) -> DirectoryIdentity | None:
        self.calls.append(subject_id)
        result = self._identities.get(subject_id)
        if isinstance(result, Exception):
            raise result
        return result


def _identity(display_name: str | None, username: str = "operator@example.invalid") -> Any:
    return DirectoryIdentity(
        provider="entra",
        subject_id=_OID,
        username=username,
        display_name=display_name,
        active=True,
    )


def _page() -> dict[str, Any]:
    return {
        "items": [
            {"seq": 1, "actor": _OID, "action_kind": "incident.open"},
            {"seq": 2, "actor": "Heimdall", "action_kind": "anomaly"},
            {"seq": 3, "actor": _OTHER, "action_kind": "incident.transition"},
            {"seq": 4, "actor": _OID, "action_kind": "incident.severity"},
        ],
        "next_cursor": None,
    }


def test_human_subject_ids_gain_a_display_label_and_agents_do_not() -> None:
    directory = _Directory({_OID: _identity("Example Operator")})
    page = _page()

    asyncio.run(ActorDisplayResolver(directory).annotate(page))  # type: ignore[arg-type]

    labels = [item.get("actor_display") for item in page["items"]]
    assert labels == ["Example Operator", None, None, "Example Operator"]
    assert directory.calls.count(_OID) == 1


def test_username_is_the_fallback_label_and_lookups_are_cached() -> None:
    directory = _Directory({_OID: _identity(None, "operator@example.invalid")})
    resolver = ActorDisplayResolver(directory)  # type: ignore[arg-type]

    first = _page()
    second = _page()
    asyncio.run(resolver.annotate(first))
    asyncio.run(resolver.annotate(second))

    assert first["items"][0]["actor_display"] == "operator@example.invalid"
    assert second["items"][0]["actor_display"] == "operator@example.invalid"
    assert directory.calls.count(_OID) == 1


def test_directory_failure_or_absence_leaves_the_page_unchanged() -> None:
    failing = _Directory({_OID: RuntimeError("directory unavailable")})
    page = _page()
    asyncio.run(ActorDisplayResolver(failing).annotate(page))  # type: ignore[arg-type]
    asyncio.run(ActorDisplayResolver(None).annotate(page))

    assert all("actor_display" not in item for item in page["items"])

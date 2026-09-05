from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "scripts/deployment/azure/verify-github-environment.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_github_environment", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload(*, reviewers: int = 1, prevent_self_review: bool = True) -> dict[str, object]:
    return {
        "can_admins_bypass": False,
        "protection_rules": [
            {
                "type": "required_reviewers",
                "prevent_self_review": prevent_self_review,
                "reviewers": [
                    {"type": "User", "reviewer": {"id": index + 1}} for index in range(reviewers)
                ],
            }
        ],
    }


def test_accepts_one_enforceable_independent_approval() -> None:
    _module().verify(_payload(), required_approvals=1)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({**_payload(), "can_admins_bypass": True}, "disable admin bypass"),
        (_payload(reviewers=0), "required reviewers"),
        (_payload(prevent_self_review=False), "block self-review"),
        ({"can_admins_bypass": False, "protection_rules": []}, "required reviewers"),
    ],
)
def test_rejects_unprotected_environment(payload: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _module().verify(payload, required_approvals=1)

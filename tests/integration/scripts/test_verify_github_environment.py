from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_PATH = _ROOT / "scripts/deployment/azure/verify-github-environment.py"
_SPEC = importlib.util.spec_from_file_location("verify_github_environment", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
verify = _MODULE.verify


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


def test_accepts_one_enforceable_environment_approval() -> None:
    verify(_payload(), required_approvals=1)


def test_rejects_missing_reviewers_self_review_and_unsupported_quorum() -> None:
    with pytest.raises(ValueError, match="reviewers"):
        verify(_payload(reviewers=0), required_approvals=1)
    with pytest.raises(ValueError, match="self-review"):
        verify(_payload(prevent_self_review=False), required_approvals=1)
    with pytest.raises(ValueError, match="exactly one"):
        verify(_payload(), required_approvals=2)
    bypass = _payload()
    bypass["can_admins_bypass"] = True
    with pytest.raises(ValueError, match="admin bypass"):
        verify(bypass, required_approvals=1)

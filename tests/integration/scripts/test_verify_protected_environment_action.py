from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_ACTION_DIR = _ROOT / ".github/actions/verify-protected-workflow-source"
_ACTION = (_ACTION_DIR / "action.yml").read_text(encoding="utf-8")
_SPEC = importlib.util.spec_from_file_location(
    "verify_protected_environment",
    _ACTION_DIR / "verify_environment.py",
)
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


def test_preflight_action_reads_one_bounded_environment_policy() -> None:
    assert "using: composite" in _ACTION
    assert "GITHUB_API_URL/repos/$TARGET_REPOSITORY/environments/$TARGET_ENVIRONMENT" in _ACTION
    assert "--connect-timeout 10 --max-time 30" in _ACTION
    assert '"${{ github.action_path }}/verify_environment.py"' in _ACTION


def test_verifier_accepts_one_enforceable_approval() -> None:
    verify(_payload(), required_approvals=1)


def test_verifier_rejects_missing_reviewers_self_review_and_bypass() -> None:
    with pytest.raises(ValueError, match="reviewers"):
        verify(_payload(reviewers=0), required_approvals=1)
    with pytest.raises(ValueError, match="self-review"):
        verify(_payload(prevent_self_review=False), required_approvals=1)
    invalid_reviewer = _payload()
    rules = invalid_reviewer["protection_rules"]
    assert isinstance(rules, list) and isinstance(rules[0], dict)
    rules[0]["reviewers"] = [{}]
    with pytest.raises(ValueError, match="reviewers"):
        verify(invalid_reviewer, required_approvals=1)
    with pytest.raises(ValueError, match="exactly one"):
        verify(_payload(), required_approvals=2)
    bypass = _payload()
    bypass["can_admins_bypass"] = True
    with pytest.raises(ValueError, match="admin bypass"):
        verify(bypass, required_approvals=1)

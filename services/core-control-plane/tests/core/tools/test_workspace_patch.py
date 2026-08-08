"""Workspace patches are content-addressed, scoped proposals only."""

from fdai.core.tools.workspace_patch import validate_workspace_patch
from fdai.shared.providers.code_workspace import (
    CodePatchKind,
    CodePatchOperation,
    CodePatchSet,
)

_BEFORE = "a" * 64
_WORKSPACE = f"workspace:sha256:{'b' * 64}"


def _patch(*operations: CodePatchOperation) -> CodePatchSet:
    return CodePatchSet(
        workspace_ref=_WORKSPACE,
        base_revision="main",
        operations=operations,
    )


def test_accepts_repository_relative_add_and_update() -> None:
    patch = _patch(
        CodePatchOperation(
            kind=CodePatchKind.UPDATE,
            path="services/core-control-plane/src/fdai/example.py",
            expected_before_sha256=_BEFORE,
            content_after="VALUE = 2\n",
        ),
        CodePatchOperation(
            kind=CodePatchKind.ADD,
            path="services/core-control-plane/tests/integration/test_example.py",
            content_after="def test_value():\n    assert True\n",
        ),
    )

    report = validate_workspace_patch(patch)

    assert report.valid
    assert report.patch_hash == patch.patch_hash


def test_rejects_runtime_generated_and_traversal_paths() -> None:
    patch = _patch(
        CodePatchOperation(
            kind=CodePatchKind.UPDATE,
            path="resolved-models.json",
            expected_before_sha256=_BEFORE,
            content_after="{}\n",
        ),
        CodePatchOperation(
            kind=CodePatchKind.ADD,
            path="../runtime.py",
            content_after="print('escape')\n",
        ),
    )

    report = validate_workspace_patch(patch)
    codes = {issue.code for issue in report.issues}

    assert not report.valid
    assert {"protected_path", "invalid_path"} <= codes


def test_rejects_duplicate_path_operations() -> None:
    patch = _patch(
        CodePatchOperation(
            kind=CodePatchKind.UPDATE,
            path="services/core-control-plane/src/fdai/example.py",
            expected_before_sha256=_BEFORE,
            content_after="VALUE = 2\n",
        ),
        CodePatchOperation(
            kind=CodePatchKind.DELETE,
            path="services/core-control-plane/src/fdai/example.py",
            expected_before_sha256=_BEFORE,
        ),
    )

    report = validate_workspace_patch(patch)

    assert "duplicate_path" in {issue.code for issue in report.issues}


def test_patch_hash_changes_with_before_and_after_content() -> None:
    first = _patch(
        CodePatchOperation(
            kind=CodePatchKind.UPDATE,
            path="services/core-control-plane/src/fdai/example.py",
            expected_before_sha256=_BEFORE,
            content_after="VALUE = 2\n",
        )
    )
    changed_before = _patch(
        CodePatchOperation(
            kind=CodePatchKind.UPDATE,
            path="services/core-control-plane/src/fdai/example.py",
            expected_before_sha256="c" * 64,
            content_after="VALUE = 2\n",
        )
    )
    changed_after = _patch(
        CodePatchOperation(
            kind=CodePatchKind.UPDATE,
            path="services/core-control-plane/src/fdai/example.py",
            expected_before_sha256=_BEFORE,
            content_after="VALUE = 3\n",
        )
    )

    assert first.patch_hash != changed_before.patch_hash
    assert first.patch_hash != changed_after.patch_hash

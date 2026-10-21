"""Immutable Rule revision identity registry checks."""

from __future__ import annotations

import importlib.util
import re
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_module() -> ModuleType:
    path = REPO_ROOT / "scripts/quality/architecture/check-rule-revision-identities.py"
    spec = importlib.util.spec_from_file_location("check_rule_revision_identities", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _copy_revision_inputs(tmp_path: Path, rule_id: str) -> tuple[Path, Path]:
    source = REPO_ROOT / "rule-catalog/catalog" / f"{rule_id}.yaml"
    definition = tmp_path / "rule-catalog/catalog" / source.name
    definition.parent.mkdir(parents=True)
    shutil.copy(source, definition)
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    policy_reference = raw["check_logic"]["reference"]
    policy = tmp_path / policy_reference
    policy.parent.mkdir(parents=True)
    shutil.copy(REPO_ROOT / policy_reference, policy)
    dockerfile = tmp_path / "services/core-control-plane/docker/Dockerfile"
    dockerfile.parent.mkdir(parents=True)
    dockerfile.write_text(
        "FROM example.invalid/go@sha256:" + ("a" * 64) + " AS opa-builder\n"
        "ARG OPA_VERSION=v1.18.2\n"
        "ARG OPA_GO_VERSION=v1.25.5\n"
        "RUN echo build\n"
        "FROM example.invalid/python@sha256:" + ("b" * 64) + " AS builder\n",
        encoding="utf-8",
    )
    for relative in (
        "services/core-control-plane/src/fdai/rule_catalog/schema/revision_identity.py",
        "services/core-control-plane/src/fdai/shared/contracts/models/rule.py",
        "services/core-control-plane/src/fdai/shared/contracts/models/_base.py",
        "services/core-control-plane/src/fdai/shared/contracts/models/enums.py",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / relative, target)
    (tmp_path / "uv.lock").write_text(
        '[[package]]\nname = "pydantic"\nversion = "2.13.4"\n'
        '[[package]]\nname = "pydantic-core"\nversion = "2.46.4"\n'
        '[[package]]\nname = "pyyaml"\nversion = "6.0.3"\n',
        encoding="utf-8",
    )
    return definition, policy


def _register_current(module: ModuleType, tmp_path: Path) -> tuple[object, ...]:
    materials = module._current_materials(tmp_path)
    return module._write_registry(
        (),
        materials,
        path=tmp_path / "rule-catalog/rule-revision-identities.json",
        artifact_root=tmp_path / "rule-catalog/revisions",
    )


def test_shipped_rule_revisions_match_the_registry() -> None:
    module = _load_module()

    assert module.violations(module._load_registry(), module.current_revisions()) == []


def test_definition_policy_and_toolchain_changes_require_a_version_bump(
    tmp_path: Path,
) -> None:
    module = _load_module()
    rule_id = "network.nsg.no-inbound-any-ssh"
    definition, policy = _copy_revision_inputs(tmp_path, rule_id)
    retained = _register_current(module, tmp_path)
    artifact_root = tmp_path / "rule-catalog/revisions"

    policy.write_text(policy.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    assert module.violations(
        retained,
        module.current_revisions(tmp_path),
        artifact_root=artifact_root,
    ) == [f"{rule_id}@1.0.0: immutable Rule revision changed"]

    shutil.copy(REPO_ROOT / "policies/network/nsg_no_inbound_any_ssh.rego", policy)
    raw = yaml.safe_load(definition.read_text(encoding="utf-8"))
    raw["severity"] = "critical"
    definition.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    assert module.violations(
        retained,
        module.current_revisions(tmp_path),
        artifact_root=artifact_root,
    ) == [f"{rule_id}@1.0.0: immutable Rule revision changed"]

    shutil.copy(
        REPO_ROOT / f"rule-catalog/catalog/{rule_id}.yaml",
        definition,
    )
    dockerfile = tmp_path / "services/core-control-plane/docker/Dockerfile"
    dockerfile.write_text(
        dockerfile.read_text(encoding="utf-8").replace(
            "OPA_GO_VERSION=v1.25.5",
            "OPA_GO_VERSION=v1.25.6",
        ),
        encoding="utf-8",
    )
    assert module.violations(
        retained,
        module.current_revisions(tmp_path),
        artifact_root=artifact_root,
    ) == [f"{rule_id}@1.0.0: immutable Rule revision changed"]


def test_version_bump_creates_a_new_retained_identity(tmp_path: Path) -> None:
    module = _load_module()
    rule_id = "network.nsg.no-inbound-any-ssh"
    definition, _ = _copy_revision_inputs(tmp_path, rule_id)
    retained = _register_current(module, tmp_path)
    raw = yaml.safe_load(definition.read_text(encoding="utf-8"))
    raw["version"] = "1.1.0"
    definition.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    current = module.current_revisions(tmp_path)

    assert module.violations(
        retained,
        current,
        artifact_root=tmp_path / "rule-catalog/revisions",
    ) == [f"{rule_id}@1.1.0: new Rule revision is not registered"]
    written = module._write_registry(
        retained,
        module._current_materials(tmp_path),
        path=tmp_path / "rule-catalog/rule-revision-identities.json",
        artifact_root=tmp_path / "rule-catalog/revisions",
    )
    assert {revision.key for revision in written} == {
        (rule_id, "1.0.0"),
        (rule_id, "1.1.0"),
    }


def test_policy_bundle_rejects_unresolved_data_dependencies(tmp_path: Path) -> None:
    module = _load_module()
    rule_id = "network.nsg.no-inbound-any-ssh"
    _, policy = _copy_revision_inputs(tmp_path, rule_id)
    policy.write_text(
        policy.read_text(encoding="utf-8") + "\nimport data.fdai.missing.shared\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="unresolved Rego data dependency"):
        module.current_revisions(tmp_path)


def test_policy_bundle_rejects_dynamic_bracket_data_references(tmp_path: Path) -> None:
    module = _load_module()
    rule_id = "network.nsg.no-inbound-any-ssh"
    _, policy = _copy_revision_inputs(tmp_path, rule_id)
    policy.write_text(
        policy.read_text(encoding="utf-8") + '\ndynamic := data["fdai"]["shared"]\n',
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="dynamic Rego data reference"):
        module.current_revisions(tmp_path)


def test_baseline_revision_cannot_be_removed_or_rewritten(tmp_path: Path) -> None:
    module = _load_module()
    rule_id = "network.nsg.no-inbound-any-ssh"
    _copy_revision_inputs(tmp_path, rule_id)
    baseline = _register_current(module, tmp_path)
    artifact_root = tmp_path / "rule-catalog/revisions"

    assert module.violations(
        (),
        (),
        baseline=baseline,
        artifact_root=artifact_root,
    ) == [f"{rule_id}@1.0.0: retained revision was removed"]
    rewritten = baseline[0].model_copy(update={"definition_digest": "sha256:" + ("f" * 64)})
    assert (
        module.violations(
            (rewritten,),
            (),
            baseline=baseline,
            artifact_root=artifact_root,
        )[0]
        == f"{rule_id}@1.0.0: retained revision was rewritten"
    )


def test_retained_artifact_bytes_are_required_and_verified(tmp_path: Path) -> None:
    module = _load_module()
    rule_id = "network.nsg.no-inbound-any-ssh"
    _copy_revision_inputs(tmp_path, rule_id)
    retained = _register_current(module, tmp_path)
    artifact_root = tmp_path / "rule-catalog/revisions"
    artifact_path = next(artifact_root.glob("*.json"))

    artifact_path.unlink()
    assert module.violations(
        retained,
        retained,
        artifact_root=artifact_root,
    ) == [f"{rule_id}@1.0.0: retained revision artifact is missing"]


def test_bare_data_root_is_rejected(tmp_path: Path) -> None:
    module = _load_module()
    rule_id = "network.nsg.no-inbound-any-ssh"
    _, policy = _copy_revision_inputs(tmp_path, rule_id)
    policy.write_text(
        policy.read_text(encoding="utf-8") + "\nall_data := object.get(data, input.key, {})\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="dynamic Rego data reference"):
        module.current_revisions(tmp_path)


def test_normalization_dependency_change_requires_version_bump(tmp_path: Path) -> None:
    module = _load_module()
    rule_id = "network.nsg.no-inbound-any-ssh"
    _copy_revision_inputs(tmp_path, rule_id)
    retained = _register_current(module, tmp_path)
    model_source = tmp_path / "services/core-control-plane/src/fdai/shared/contracts/models/rule.py"
    model_source.write_text(
        model_source.read_text(encoding="utf-8") + "\n# normalization changed\n",
        encoding="utf-8",
    )

    assert (
        module.violations(
            retained,
            module.current_revisions(tmp_path),
            artifact_root=tmp_path / "rule-catalog/revisions",
        )[0]
        == f"{rule_id}@1.0.0: immutable Rule revision changed"
    )


def test_history_check_requires_an_explicit_base_ref() -> None:
    module = _load_module()

    with pytest.raises(SystemExit, match="--base-ref is required"):
        module._optional_baseline_registry(None)


def test_string_hash_cannot_hide_dynamic_data_reference(tmp_path: Path) -> None:
    module = _load_module()
    rule_id = "network.nsg.no-inbound-any-ssh"
    _, policy = _copy_revision_inputs(tmp_path, rule_id)
    policy.write_text(
        policy.read_text(encoding="utf-8")
        + '\nhash := "#"; hidden := object.get(data, input.key, {})\n',
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="dynamic Rego data reference"):
        module.current_revisions(tmp_path)


def test_static_data_prefix_retains_the_complete_package_subtree(tmp_path: Path) -> None:
    module = _load_module()
    rule_id = "network.nsg.no-inbound-any-ssh"
    _, policy = _copy_revision_inputs(tmp_path, rule_id)
    shared = tmp_path / "policies/shared"
    shared.mkdir(parents=True)
    (shared / "root.rego").write_text(
        "package fdai.shared\nimport rego.v1\nvalue := true\n",
        encoding="utf-8",
    )
    (shared / "child.rego").write_text(
        "package fdai.shared.child\nimport rego.v1\nvalue := true\n",
        encoding="utf-8",
    )
    policy.write_text(
        policy.read_text(encoding="utf-8") + "\nselected := data.fdai.shared[input.key]\n",
        encoding="utf-8",
    )

    (revision,) = module.current_revisions(tmp_path)
    assert {artifact.path for artifact in revision.artifacts} == {
        "policies/network/nsg_no_inbound_any_ssh.rego",
        "policies/shared/child.rego",
        "policies/shared/root.rego",
    }


def test_own_package_prefix_retains_child_modules(tmp_path: Path) -> None:
    module = _load_module()
    rule_id = "network.nsg.no-inbound-any-ssh"
    _, policy = _copy_revision_inputs(tmp_path, rule_id)
    child = tmp_path / "policies/network/shared_child.rego"
    child.write_text(
        "package fdai.network.nsg_no_inbound_any_ssh.child\nimport rego.v1\nvalue := true\n",
        encoding="utf-8",
    )
    policy.write_text(
        policy.read_text(encoding="utf-8")
        + "\nselected := data.fdai.network.nsg_no_inbound_any_ssh[input.key]\n",
        encoding="utf-8",
    )

    (revision,) = module.current_revisions(tmp_path)
    assert {artifact.path for artifact in revision.artifacts} == {
        "policies/network/nsg_no_inbound_any_ssh.rego",
        "policies/network/shared_child.rego",
    }


def _write_go_builder(
    tmp_path: Path, *, go_version: str, digest: str, opa: str = "v1.18.2"
) -> None:
    (tmp_path / "services/core-control-plane/docker/Dockerfile").write_text(
        f"FROM example.invalid/library/golang@sha256:{digest} AS opa-builder\n"
        f"ARG OPA_VERSION={opa}\n"
        f"ARG OPA_GO_VERSION={go_version}\n"
        "RUN echo build\n"
        "FROM example.invalid/python@sha256:" + ("b" * 64) + " AS builder\n",
        encoding="utf-8",
    )


def _violations_after(
    module: ModuleType, tmp_path: Path, retained: tuple[object, ...]
) -> list[str]:
    return module.violations(
        retained,
        module.current_revisions(tmp_path),
        artifact_root=tmp_path / "rule-catalog/revisions",
    )


def test_go_patch_release_keeps_rule_identity_but_other_toolchain_changes_do_not(
    tmp_path: Path,
) -> None:
    module = _load_module()
    rule_id = "network.nsg.no-inbound-any-ssh"
    _copy_revision_inputs(tmp_path, rule_id)
    baseline_version, baseline_digest = module._GO_IDENTITY_BASELINES["go1.27"]
    _write_go_builder(
        tmp_path, go_version=baseline_version, digest=baseline_digest.removeprefix("sha256:")
    )
    retained = _register_current(module, tmp_path)

    _write_go_builder(tmp_path, go_version="go1.27.9", digest="c" * 64)
    assert _violations_after(module, tmp_path, retained) == []

    _write_go_builder(tmp_path, go_version="go1.28.0", digest="c" * 64)
    assert _violations_after(module, tmp_path, retained) == [
        f"{rule_id}@1.0.0: immutable Rule revision changed"
    ]

    _write_go_builder(
        tmp_path,
        go_version="go1.27.9",
        digest="c" * 64,
        opa="v1.19.0",
    )
    assert _violations_after(module, tmp_path, retained) == [
        f"{rule_id}@1.0.0: immutable Rule revision changed"
    ]


def test_shipped_go_pin_is_a_patch_of_the_retained_baseline_series() -> None:
    module = _load_module()
    dockerfile = (REPO_ROOT / "services/core-control-plane/docker/Dockerfile").read_text(
        encoding="utf-8"
    )
    pin = re.search(r"^ARG OPA_GO_VERSION=(go\d+\.\d+)\.\d+$", dockerfile, re.MULTILINE)

    assert pin is not None
    assert pin.group(1) in module._GO_IDENTITY_BASELINES

#!/usr/bin/env python3
"""Validate truthful runtime-support claims for every catalog ActionType.

The manifest separates catalog presence from runtime routing, activation mode,
effect observation, recovery, and retained evidence. Source inspection can
prove a route is represented in composition, but it never upgrades a claim to
deployed or current-revision evidence.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST = Path("config/action-type-runtime-support.json")
DEFAULT_SCHEMA = Path("config/action-type-runtime-support.schema.json")
RECEIPT_LEVELS = frozenset({"historical_receipt", "current_revision_receipt"})
SUPPORTED_SOURCE_STATUSES = frozenset({"wired", "conditional", "source_only", "declared_only"})
ATTESTATION_REPOSITORY = "dotnetpower/fdai"


@dataclass(frozen=True, slots=True)
class CatalogAction:
    """Minimal catalog facts needed to validate one support claim."""

    ref: str
    name: str
    version: str
    execution_path: str
    default_mode: str
    rollback_contract: str
    irreversible: bool
    path: str


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} MUST contain a JSON object")
    return value


def _repo_path(root: Path, value: object, field: str, *, directory: bool = False) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError(f"{field} MUST be a repository-relative path")
    candidate = (root / value).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError(f"{field} MUST stay inside the repository")
    exists = candidate.is_dir() if directory else candidate.is_file()
    if not exists:
        kind = "directory" if directory else "file"
        raise ValueError(f"{field} references a missing {kind}: {value}")
    return candidate


def _load_catalog(root: Path, relative: object) -> dict[str, CatalogAction]:
    catalog_root = _repo_path(root, relative, "catalog_root", directory=True)
    actions: dict[str, CatalogAction] = {}
    for path in sorted(catalog_root.glob("*.yaml")):
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"{path.relative_to(root)} MUST contain a YAML object")
        fields = {
            key: value.get(key)
            for key in (
                "name",
                "version",
                "execution_path",
                "default_mode",
                "rollback_contract",
                "irreversible",
            )
        }
        if not all(
            isinstance(fields[key], str) and fields[key] for key in fields if key != "irreversible"
        ):
            raise ValueError(f"{path.relative_to(root)} has incomplete support facts")
        if not isinstance(fields["irreversible"], bool):
            raise ValueError(f"{path.relative_to(root)} irreversible MUST be boolean")
        name = str(fields["name"])
        version = str(fields["version"])
        ref = f"{name}@{version}"
        if ref in actions:
            raise ValueError(f"duplicate catalog ActionType: {ref}")
        actions[ref] = CatalogAction(
            ref=ref,
            name=name,
            version=version,
            execution_path=str(fields["execution_path"]),
            default_mode=str(fields["default_mode"]),
            rollback_contract=str(fields["rollback_contract"]),
            irreversible=bool(fields["irreversible"]),
            path=path.relative_to(root).as_posix(),
        )
    if not actions:
        raise ValueError("ActionType catalog is empty")
    return actions


def _schema_errors(manifest: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    errors: list[str] = []
    for error in sorted(
        validator.iter_errors(manifest),
        key=lambda item: tuple(str(part) for part in item.path),
    ):
        location = ".".join(str(part) for part in error.path) or "<root>"
        errors.append(f"{location}: {error.message}")
    return errors


def _named_assignments(tree: ast.AST) -> dict[str, list[ast.expr]]:
    assignments: dict[str, list[ast.expr]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments.setdefault(target.id, []).append(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                assignments.setdefault(node.target.id, []).append(node.value)
    return assignments


def _string_values(
    node: ast.expr,
    assignments: dict[str, list[ast.expr]],
    *,
    stack: frozenset[str] = frozenset(),
) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.Name):
        if node.id in stack:
            return set()
        values: set[str] = set()
        for assigned in assignments.get(node.id, []):
            values.update(_string_values(assigned, assignments, stack=stack | {node.id}))
        return values
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return {
            value
            for element in node.elts
            for value in _string_values(element, assignments, stack=stack)
        }
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"frozenset", "list", "set", "tuple"}
        and len(node.args) == 1
    ):
        return _string_values(node.args[0], assignments, stack=stack)
    return set()


def _mapping_keys(node: ast.expr) -> set[str]:
    if not isinstance(node, ast.Dict):
        return set()
    return {
        key.value
        for key in node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def _subscript_keys(tree: ast.AST, symbol: str) -> set[str]:
    keys: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id == symbol
                and isinstance(target.slice, ast.Constant)
                and isinstance(target.slice.value, str)
            ):
                keys.add(target.slice.value)
    return keys


def _source_names(root: Path, assertion: dict[str, Any]) -> set[str]:
    kind = assertion["kind"]
    if kind == "catalog_execution_path":
        raise AssertionError("catalog assertions are resolved without source parsing")
    path = _repo_path(root, assertion["path"], "binding source_assertion.path")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    assignments = _named_assignments(tree)
    symbol = str(assertion["symbol"])
    if kind == "subscript_key":
        value = str(assertion["value"])
        return {value} if value in _subscript_keys(tree, symbol) else set()
    candidates = assignments.get(symbol, [])
    if not candidates:
        return set()
    if kind == "mapping_keys":
        return {key for candidate in candidates for key in _mapping_keys(candidate)}
    values = {value for candidate in candidates for value in _string_values(candidate, assignments)}
    if kind == "constant_value" and len(values) > 1:
        return set()
    return values


def _refs_for_names(
    names: set[str],
    catalog: dict[str, CatalogAction],
    errors: list[str],
    *,
    binding_id: str,
) -> set[str]:
    by_name = {action.name: action.ref for action in catalog.values()}
    unknown = sorted(names - set(by_name))
    if unknown:
        errors.append(f"binding {binding_id} names unknown ActionTypes: {unknown}")
    return {by_name[name] for name in names if name in by_name}


def _validate_reference_paths(
    root: Path,
    support_profiles: dict[str, Any],
    errors: list[str],
) -> None:
    for profile_id, profile in support_profiles.items():
        for section in ("effect_observation", "recovery", "evidence"):
            claim = profile[section]
            refs = claim["refs"]
            for index, reference in enumerate(refs):
                try:
                    _repo_path(
                        root,
                        reference["path"],
                        f"support_profiles.{profile_id}.{section}.refs[{index}].path",
                    )
                except ValueError as exc:
                    errors.append(str(exc))
                    continue
                symbol = reference.get("symbol")
                if symbol is not None and not _source_reference_has_symbol(root, reference):
                    errors.append(
                        f"profile {profile_id} {section} source symbol is missing: "
                        f"{reference['path']}::{symbol}"
                    )
            status = claim.get("status")
            if status in SUPPORTED_SOURCE_STATUSES and not refs:
                errors.append(f"profile {profile_id} {section} status {status} requires refs")
            if status in {"missing", "not_applicable"} and refs:
                errors.append(f"profile {profile_id} {section} status {status} forbids refs")
        evidence = profile["evidence"]
        if not evidence["refs"]:
            errors.append(f"profile {profile_id} evidence requires at least one ref")
        if evidence["level"] in RECEIPT_LEVELS:
            for reference in evidence["refs"]:
                if "revision" not in reference:
                    errors.append(
                        f"profile {profile_id} receipt evidence requires an immutable revision"
                    )
                    continue
                errors.extend(
                    _receipt_reference_errors(
                        root,
                        reference,
                        level=evidence["level"],
                        profile_id=profile_id,
                    )
                )


def _source_reference_has_symbol(root: Path, reference: dict[str, Any]) -> bool:
    path = _repo_path(root, reference["path"], "support source reference")
    if path.suffix != ".py":
        return False
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    symbol = str(reference["symbol"])
    return any(
        (
            isinstance(node, (ast.Assign, ast.AnnAssign))
            and any(
                isinstance(target, ast.Name) and target.id == symbol
                for target in (node.targets if isinstance(node, ast.Assign) else (node.target,))
            )
        )
        or isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == symbol
        for node in ast.walk(tree)
    )


def _mapping_records(value: object) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    if isinstance(value, dict):
        record = {str(key): nested for key, nested in value.items()}
        records.append(record)
        for nested in value.values():
            records.extend(_mapping_records(nested))
    elif isinstance(value, list):
        for nested in value:
            records.extend(_mapping_records(nested))
    return records


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _canonical_receipt_digest(record: dict[str, object]) -> str:
    payload = {key: value for key, value in record.items() if key != "receipt_digest"}
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _receipt_records(payload: object, *, revision: str) -> list[dict[str, object]]:
    revision_fields = ("source_revision", "base_revision", "fdai_revision", "revision")
    identity_fields = ("receipt_id", "receipt_ref")
    return [
        record
        for record in _mapping_records(payload)
        if any(isinstance(record.get(key), str) and record[key] for key in identity_fields)
        and _is_sha256(record.get("receipt_digest"))
        and record["receipt_digest"] == _canonical_receipt_digest(record)
        and record.get("effect_verified") is True
        and any(record.get(key) == revision for key in revision_fields)
    ]


def _receipt_reference_errors(
    root: Path,
    reference: dict[str, Any],
    *,
    level: str,
    profile_id: str,
) -> list[str]:
    errors: list[str] = []
    path = _repo_path(root, reference["path"], "receipt evidence path")
    revision = str(reference["revision"])
    if path.suffix != ".json":
        return [f"profile {profile_id} receipt evidence MUST reference JSON"]
    if set(revision) == {"0"}:
        errors.append(f"profile {profile_id} receipt revision MUST NOT be all zeroes")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"profile {profile_id} receipt evidence is invalid JSON: {exc}"]
    if not _receipt_records(payload, revision=revision):
        errors.append(
            f"profile {profile_id} has no single revision-bound, digest-identified, "
            "effect-verified receipt record"
        )
    completed = subprocess.run(
        ["git", "cat-file", "-e", f"{revision}^{{commit}}"],
        cwd=root,
        check=False,
        capture_output=True,
        timeout=30,
    )
    if completed.returncode != 0:
        errors.append(f"profile {profile_id} receipt revision is not a repository commit")
    if level == "current_revision_receipt":
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
        if revision != head:
            errors.append(f"profile {profile_id} receipt revision is not current HEAD")
    attestation_path = reference.get("attestation_path")
    signer_workflow = reference.get("signer_workflow")
    if not isinstance(attestation_path, str) or not isinstance(signer_workflow, str):
        errors.append(f"profile {profile_id} receipt evidence requires a signed attestation")
        return errors
    try:
        bundle = _repo_path(root, attestation_path, "receipt attestation path")
    except ValueError as exc:
        errors.append(str(exc))
        return errors
    try:
        subprocess.run(
            [
                "gh",
                "attestation",
                "verify",
                str(path),
                "--bundle",
                str(bundle),
                "--repo",
                ATTESTATION_REPOSITORY,
                "--signer-workflow",
                signer_workflow,
                "--source-digest",
                revision,
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        errors.append(f"profile {profile_id} receipt attestation verification failed")
    return errors


def _receipt_binds_action(
    root: Path,
    reference: dict[str, Any],
    action: CatalogAction,
) -> bool:
    path = _repo_path(root, reference["path"], "receipt evidence path")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    revision = str(reference["revision"])
    return any(
        record.get("action_type") == action.name
        or record.get("action_type_ref") in {action.name, action.ref}
        for record in _receipt_records(payload, revision=revision)
    )


def _binding_members(actions: dict[str, Any]) -> dict[str, set[str]]:
    members: dict[str, set[str]] = {}
    for action_ref, claim in actions.items():
        for binding_ref in claim["bindings"]:
            members.setdefault(binding_ref, set()).add(action_ref)
    return members


def _validate_bindings(
    root: Path,
    manifest: dict[str, Any],
    catalog: dict[str, CatalogAction],
    errors: list[str],
) -> None:
    bindings = manifest["bindings"]
    profiles = manifest["support_profiles"]
    actions = manifest["actions"]
    members = _binding_members(actions)
    for action_ref, claim in actions.items():
        for binding_ref, profile_ref in claim["bindings"].items():
            if binding_ref not in bindings:
                errors.append(f"{action_ref} references unknown binding {binding_ref}")
            if profile_ref not in profiles:
                errors.append(f"{action_ref} references unknown support profile {profile_ref}")
    for binding_id, binding in bindings.items():
        assertion = binding["source_assertion"]
        kind = assertion["kind"]
        if kind == "catalog_execution_path":
            expected = {
                action.ref
                for action in catalog.values()
                if action.execution_path == assertion["value"]
            }
            try:
                asserted_root = _repo_path(
                    root,
                    assertion["path"],
                    f"bindings.{binding_id}.source_assertion.path",
                    directory=True,
                )
                catalog_root = _repo_path(
                    root, manifest["catalog_root"], "catalog_root", directory=True
                )
                if asserted_root != catalog_root:
                    errors.append(f"binding {binding_id} catalog assertion uses the wrong root")
            except ValueError as exc:
                errors.append(str(exc))
        else:
            try:
                names = _source_names(root, assertion)
            except (SyntaxError, ValueError) as exc:
                errors.append(f"binding {binding_id} source assertion failed: {exc}")
                continue
            expected = _refs_for_names(names, catalog, errors, binding_id=binding_id)
        actual = members.get(binding_id, set())
        if actual != expected:
            errors.append(
                f"binding {binding_id} membership mismatch: "
                f"manifest={sorted(actual)} source={sorted(expected)}"
            )
        mode_support = binding["mode_support"]
        conditional = (
            binding["route_status"] == "conditional" or "conditional" in mode_support.values()
        )
        if conditional and not binding["activation_conditions"]:
            errors.append(f"binding {binding_id} is conditional but has no activation conditions")
        if not conditional and binding["activation_conditions"]:
            errors.append(f"binding {binding_id} has unconditional modes but declares conditions")
        if binding["route_status"] == "conditional" and "wired" in mode_support.values():
            errors.append(f"binding {binding_id} cannot wire a mode through a conditional route")
        if set(mode_support.values()) == {"unsupported"}:
            errors.append(f"binding {binding_id} supports no runtime mode")


def _demo_ready(
    binding: dict[str, Any],
    profile: dict[str, Any],
) -> bool:
    return (
        binding["route_status"] == "wired"
        and binding["mode_support"]["enforce"] == "wired"
        and profile["delivery_status"] == "executable"
        and profile["effect_observation"]["status"] == "wired"
        and profile["recovery"]["status"] in {"wired", "not_applicable"}
        and profile["evidence"]["level"] == "current_revision_receipt"
    )


def validate(
    *,
    root: Path = REPO_ROOT,
    manifest_path: Path = DEFAULT_MANIFEST,
    schema_path: Path = DEFAULT_SCHEMA,
) -> list[str]:
    """Return every support-manifest violation without importing runtime code."""

    errors: list[str] = []
    try:
        manifest = _load_json(root / manifest_path)
        schema = _load_json(root / schema_path)
    except ValueError as exc:
        return [str(exc)]
    errors.extend(_schema_errors(manifest, schema))
    if errors:
        return errors
    try:
        catalog = _load_catalog(root, manifest["catalog_root"])
    except ValueError as exc:
        return [str(exc)]
    actions = manifest["actions"]
    missing = sorted(set(catalog) - set(actions))
    extra = sorted(set(actions) - set(catalog))
    if missing:
        errors.append(f"manifest is missing catalog ActionTypes: {missing}")
    if extra:
        errors.append(f"manifest contains unknown ActionTypes: {extra}")
    _validate_reference_paths(root, manifest["support_profiles"], errors)
    _validate_bindings(root, manifest, catalog, errors)
    for action_ref, claim in actions.items():
        if action_ref not in catalog:
            continue
        if not claim["bindings"] and "unsupported_reason" not in claim:
            errors.append(f"{action_ref} has no binding and no unsupported_reason")
        for binding_ref, profile_ref in claim["bindings"].items():
            binding = manifest["bindings"].get(binding_ref)
            profile = manifest["support_profiles"].get(profile_ref)
            if binding is None or profile is None:
                continue
            for section in ("effect_observation", "recovery"):
                support = profile[section]
                if support["status"] == "wired" and not any(
                    reference.get("symbol") is not None
                    and catalog[action_ref].name
                    in _source_names(
                        root,
                        {
                            "kind": "set_values",
                            "path": reference["path"],
                            "symbol": reference["symbol"],
                        },
                    )
                    for reference in support["refs"]
                ):
                    errors.append(
                        f"{action_ref} profile {profile_ref} {section} wired claim "
                        "lacks an action-bound source symbol"
                    )
            if profile["evidence"]["level"] in RECEIPT_LEVELS:
                if not any(
                    _receipt_binds_action(root, reference, catalog[action_ref])
                    for reference in profile["evidence"]["refs"]
                    if str(reference["path"]).endswith(".json")
                ):
                    errors.append(f"{action_ref} receipt evidence does not bind the ActionType")
            if _demo_ready(binding, profile):
                evidence = profile["evidence"]["refs"]
                if not all(reference.get("revision") for reference in evidence):
                    errors.append(
                        f"{action_ref} derives demo-ready without revision-bound evidence"
                    )
    return errors


def _render_markdown(manifest: dict[str, Any], catalog: dict[str, CatalogAction]) -> str:
    lines = [
        "| ActionType | Path | Runtime surfaces | Observation | Recovery | Evidence | Demo ready |",
        "|---|---|---|---|---|---|---|",
    ]
    for action_ref in sorted(catalog):
        action = catalog[action_ref]
        claim = manifest["actions"][action_ref]
        surfaces: list[str] = []
        observation: set[str] = set()
        recovery: set[str] = set()
        evidence: set[str] = set()
        ready = False
        for binding_ref, profile_ref in sorted(claim["bindings"].items()):
            binding = manifest["bindings"][binding_ref]
            profile = manifest["support_profiles"][profile_ref]
            surfaces.append(
                f"{binding['runtime_surface']}:{binding['route_status']}"
                f"[shadow={binding['mode_support']['shadow']},"
                f"enforce={binding['mode_support']['enforce']}]"
            )
            observation.add(profile["effect_observation"]["status"])
            recovery.add(profile["recovery"]["status"])
            evidence.add(profile["evidence"]["level"])
            ready = ready or _demo_ready(binding, profile)
        if not surfaces:
            surfaces = ["unsupported"]
            observation = {"missing"}
            recovery = {"missing"}
            evidence = {"source_only"}
        cells = (
            action_ref,
            action.execution_path,
            "<br>".join(surfaces),
            ", ".join(sorted(observation)),
            ", ".join(sorted(recovery)),
            ", ".join(sorted(evidence)),
            "yes" if ready else "no",
        )
        lines.append("| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--format", choices=("summary", "markdown"), default="summary")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    errors = validate(root=root, manifest_path=args.manifest, schema_path=args.schema)
    if errors:
        for error in errors:
            print(f"action-type-runtime-support: {error}", file=sys.stderr)
        return 1
    manifest = _load_json(root / args.manifest)
    catalog = _load_catalog(root, manifest["catalog_root"])
    if args.format == "markdown":
        print(_render_markdown(manifest, catalog))
    else:
        bound = sum(bool(claim["bindings"]) for claim in manifest["actions"].values())
        print(
            "action-type-runtime-support: OK "
            f"catalog={len(catalog)} bound={bound} unsupported={len(catalog) - bound}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

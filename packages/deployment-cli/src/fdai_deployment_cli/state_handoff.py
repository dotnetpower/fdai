"""Private Terraform state comparison, without migration or backend authority."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fdai_deployment_cli.cli_help import command
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.plan_input import read_plan_input
from fdai_deployment_cli.private_output import write_private_output

_MAX_DEPTH = 32


def compare_foundation_state(
    local: dict[str, object], remote: dict[str, object], plan: dict[str, object]
) -> dict[str, object]:
    """Compare state copies and the remote plan's prior managed identities.

    Inputs must come from a protected, independently observed state handoff.
    Equality is not evidence of their origin, lease, storage protection, or
    authorization. This function never permits deletion of the recovery cache.
    """

    local_identities = _state_identities(local)
    remote_identities = _state_identities(remote)
    local_serial = _state_serial(local)
    remote_serial = _state_serial(remote)
    if local["lineage"] != remote["lineage"] or remote_serial not in {
        local_serial,
        local_serial + 1,
    }:
        raise ValueError("foundation state lineage or serial differs after handoff")
    if local_identities != remote_identities:
        raise ValueError("foundation state resource identities differ after handoff")
    local_content = {
        key: value for key, value in local.items() if key not in {"serial", "check_results"}
    }
    remote_content = {
        key: value for key, value in remote.items() if key not in {"serial", "check_results"}
    }
    if local_content != remote_content or _check_result_digests(local) != _check_result_digests(
        remote
    ):
        raise ValueError("foundation state content differs after handoff")
    local_digest = canonical_digest(local)
    version = plan.get("format_version")
    if (
        not isinstance(version, str)
        or version not in {"1.1", "1.2"}
        or plan.get("complete") is not True
        or plan.get("errored") is not False
        or plan.get("applyable") is not False
    ):
        raise ValueError("foundation handoff requires a complete non-errored no-change plan")
    no_change_after: dict[str, dict[str, object]] = {}
    for item in _array(plan.get("resource_changes", [])):
        resource_change = _object(item)
        if "previous_address" in resource_change:
            raise ValueError("foundation handoff plan contains an address move")
        address = _text(resource_change.get("address"))
        if address in no_change_after:
            raise ValueError("foundation handoff plan contains duplicate resource changes")
        resource_delta = _object(resource_change.get("change"))
        _no_change(resource_delta)
        no_change_after[address] = _object(resource_delta["after"])
    for item in _array(plan.get("resource_drift", [])):
        _refresh_only_drift(_object(item), no_change_after)
    if _array(plan.get("deferred_changes", [])):
        raise ValueError("foundation handoff plan contains deferred changes")
    for output_change in _object(plan.get("output_changes", {})).values():
        _no_change(output_change)
    for check in _array(plan.get("checks", [])):
        if _object(check).get("status") != "pass":
            raise ValueError("foundation handoff plan checks must pass")
    prior = _object(_object(plan.get("prior_state")).get("values"))
    prior_identities: dict[str, str] = {}
    _plan_identities(_object(prior.get("root_module")), prior_identities, depth=0)
    if prior_identities != remote_identities:
        raise ValueError("foundation handoff plan does not describe the compared remote state")
    return {
        "schema_version": "fdai.foundation-state-comparison.v1",
        "state": "review",
        "comparison_verified": True,
        "state_digest": local_digest,
        "plan_digest": canonical_digest(plan),
        "managed_resource_count": len(remote_identities),
        "remote_backend_authority_verified": False,
        "local_state_deletion_authorized": False,
        "mutation_performed": False,
        "subscription_ready": False,
    }


def _check_result_digests(state: dict[str, object]) -> tuple[str, ...]:
    return tuple(
        sorted(canonical_digest(_object(item)) for item in _array(state.get("check_results", [])))
    )


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("foundation handoff contains an invalid JSON object")
    return {key: item for key, item in value.items()}


def _array(value: object) -> list[object]:
    if not isinstance(value, list) or len(value) > 10_000:
        raise ValueError("foundation handoff contains an invalid JSON array")
    return list(value)


def _text(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ValueError("foundation handoff contains an invalid resource identity")
    return value


def _no_change(value: object) -> None:
    change = _object(value)
    if (
        "before" not in change
        or "after" not in change
        or change.get("actions") != ["no-op"]
        or change.get("importing") is not None
        or change.get("before") != change.get("after")
    ):
        raise ValueError("foundation handoff plan contains a change")


def _refresh_only_drift(
    drift: dict[str, object], no_change_after: dict[str, dict[str, object]]
) -> None:
    if "previous_address" in drift:
        raise ValueError("foundation handoff drift contains an address move")
    address = _text(drift.get("address"))
    change = _object(drift.get("change"))
    before = _object(change.get("before"))
    after = _object(change.get("after"))
    if (
        change.get("actions") != ["update"]
        or change.get("importing") is not None
        or before == after
        or before.get("id") != after.get("id")
        or no_change_after.get(address) != after
    ):
        raise ValueError("foundation handoff plan contains unclosed resource drift")


def _add_identity(identities: dict[str, str], address: str, resource_id: object) -> None:
    if address in identities:
        raise ValueError("foundation handoff contains duplicate managed identities")
    identities[address] = _text(resource_id)


def _state_identities(state: dict[str, object]) -> dict[str, str]:
    if (
        type(state.get("version")) is not int
        or state["version"] != 4
        or not isinstance(state.get("lineage"), str)
        or not state["lineage"]
    ):
        raise ValueError("foundation handoff requires version-4 state with lineage and serial")
    _state_serial(state)
    identities: dict[str, str] = {}
    for entry in _array(state.get("resources")):
        resource = _object(entry)
        if resource.get("mode") == "data":
            continue
        if resource.get("mode") != "managed":
            raise ValueError("foundation state resource mode is invalid")
        base = _text(resource.get("type")) + "." + _text(resource.get("name"))
        if "module" in resource:
            base = _text(resource["module"]) + "." + base
        for entry in _array(resource.get("instances")):
            instance = _object(entry)
            if instance.get("status") is not None or instance.get("deposed") is not None:
                raise ValueError("foundation state contains a tainted or deposed instance")
            index = instance.get("index_key")
            if index is None:
                suffix = ""
            elif isinstance(index, str):
                suffix = "[" + json.dumps(index, ensure_ascii=False) + "]"
            elif type(index) is int and index >= 0:
                suffix = f"[{index}]"
            else:
                raise ValueError("foundation state instance index is invalid")
            _add_identity(identities, base + suffix, _object(instance.get("attributes")).get("id"))
    if not identities:
        raise ValueError("foundation handoff cannot verify empty managed state")
    return identities


def _state_serial(state: dict[str, object]) -> int:
    serial = state.get("serial")
    if type(serial) is not int or serial < 0:
        raise ValueError("foundation handoff requires version-4 state with lineage and serial")
    return serial


def _plan_identities(module: dict[str, object], identities: dict[str, str], *, depth: int) -> None:
    if depth > _MAX_DEPTH:
        raise ValueError("foundation handoff plan exceeds the module depth limit")
    for entry in _array(module.get("resources", [])):
        resource = _object(entry)
        if resource.get("mode") == "data":
            continue
        if resource.get("mode") != "managed":
            raise ValueError("foundation plan resource mode is invalid")
        _add_identity(
            identities,
            _text(resource.get("address")),
            _object(resource.get("values")).get("id"),
        )
    for child in _array(module.get("child_modules", [])):
        _plan_identities(_object(child), identities, depth=depth + 1)


def register_state_handoff_command(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register a file-only comparison command; no Azure or Terraform execution."""

    parser = command(
        commands,
        "verify-state-handoff",
        "Compare local state copies and a zero-change plan; no migration",
    )
    parser.add_argument("--local-state", type=Path, required=True)
    parser.add_argument("--remote-state", type=Path, required=True)
    parser.add_argument("--plan-json", type=Path, required=True)
    parser.add_argument("--output-receipt", type=Path, required=True)
    parser.add_argument("--output", choices=("text", "json"), default="text")
    parser.set_defaults(handler=_verify_state_handoff)


def _verify_state_handoff(args: argparse.Namespace) -> int:
    result = compare_foundation_state(
        read_plan_input(args.local_state),
        read_plan_input(args.remote_state),
        read_plan_input(args.plan_json),
    )
    write_private_output(
        args.output_receipt, json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n"
    )
    print(
        json.dumps(result, sort_keys=True, separators=(",", ":"))
        if args.output == "json"
        else "state copies match; backend authority and recovery-cache deletion remain unverified"
    )
    return 0

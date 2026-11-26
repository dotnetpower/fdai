"""Bound a successor to a claimed partial Foundation recovery and two pending repairs."""

from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Mapping
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest, load_json_object
from fdai_deployment_cli.private_output import read_private_bytes
from genesis_foundation_recovery import _changes, _same_known, _state_instances

APPLICATION = "azapi_resource.app_resource_group"
VM = "module.bootstrap.azurerm_linux_virtual_machine.runner[0]"
DELEGATE = (
    "module.bootstrap.azurerm_role_assignment.runner_subscription_observation_role_delegate[0]"
)
REPAIRS = (
    (b'    caching = "ReadWrite"\n', b'    caching = "ReadOnly"\n'),
    (
        b"for role in data.azurerm_role_definition.subscription_observation : "
        b"role.role_definition_id\n",
        b"for role in data.azurerm_role_definition.subscription_observation : "
        b"basename(role.role_definition_id)\n",
    ),
)
_GUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
_SCOPED_ROLE = re.compile(
    r"/subscriptions/"
    + _GUID
    + r"/providers/Microsoft.Authorization/roleDefinitions/("
    + _GUID
    + r")"
)


def require_pending_repairs(original: Path, current: Path) -> None:
    """Allow exactly the ephemeral cache and scoped-role GUID corrections in bootstrap main."""
    expected = original.read_bytes()
    for before, after in REPAIRS:
        if expected.count(before) != 1:
            raise ValueError("Foundation successor original repair input is unsupported")
        expected = expected.replace(before, after, 1)
    if current.read_bytes() != expected:
        raise ValueError("Foundation successor changes more than the two pending repairs")


def repaired_values(address: str, values: dict[str, object]) -> dict[str, object]:
    """Compute only the allowed known-value repair, preserving every authority operand."""
    repaired = copy.deepcopy(values)
    if address == VM:
        disks = repaired.get("os_disk")
        if not isinstance(disks, list) or len(disks) != 1 or not isinstance(disks[0], dict):
            raise ValueError("Foundation successor VM disk input is incomplete")
        disk = disks[0]
        if disk.get("caching") != "ReadWrite" or disk.get("diff_disk_settings") != [
            {"option": "Local", "placement": "ResourceDisk"}
        ]:
            raise ValueError("Foundation successor VM disk repair is unsupported")
        disk["caching"] = "ReadOnly"
    elif address == DELEGATE:
        condition = repaired.get("condition")
        if not isinstance(condition, str) or repaired.get("condition_version") != "2.0":
            raise ValueError("Foundation successor delegation condition is incomplete")
        condition, count = _SCOPED_ROLE.subn(r"\1", condition)
        if count != 6:
            raise ValueError("Foundation successor requires the original three role operands twice")
        repaired["condition"] = condition
    else:
        raise ValueError("Foundation successor pending resource is outside repair scope")
    return repaired


def validate_successor_plan(
    projection: Mapping[str, object],
    predecessor: Mapping[str, object],
    state: Mapping[str, object],
) -> dict[str, object]:
    """Preserve every recorded resource and permit only two absent, originally pending creates."""
    if (
        projection.get("complete") is not True
        or projection.get("errored") is not False
        or projection.get("applyable") is not True
        or projection.get("deferred_changes")
        or canonical_bytes(projection.get("variables"))
        != canonical_bytes(predecessor.get("variables"))
    ):
        raise ValueError("Foundation successor is incomplete or changes original inputs")
    checks = projection.get("checks", [])
    if not isinstance(checks, list) or any(
        not isinstance(check, dict) or check.get("status") not in {"pass", "unknown"}
        for check in checks
    ):
        raise ValueError("Foundation successor plan checks failed")
    changes, prior = _changes(projection), _changes(predecessor)
    existing = _state_instances(state)
    if (
        set(changes) != set(prior)
        or not existing.keys() <= changes.keys()
        or APPLICATION not in existing
    ):
        raise ValueError("Foundation successor inventory or application ownership differs")
    pending = []
    for address, entry in changes.items():
        previous = prior[address]
        change, old = entry.get("change"), previous.get("change")
        if (
            not isinstance(change, dict)
            or not isinstance(old, dict)
            or entry.get("type") != previous.get("type")
            or entry.get("mode") != previous.get("mode")
            or entry.get("previous_address") is not None
            or change.get("importing") is not None
        ):
            raise ValueError("Foundation successor resource identity changed")
        if entry.get("mode") == "data":
            if change.get("actions") not in (["read"], ["no-op"]):
                raise ValueError("Foundation successor data resource has effects")
            continue
        after = change.get("after")
        if entry.get("mode") != "managed" or not isinstance(after, dict):
            raise ValueError("Foundation successor resource values are incomplete")
        if address in existing:
            expected = existing[address]
            if (
                old.get("actions") not in (["no-op"], ["create"])
                or change.get("actions") != ["no-op"]
                or change.get("before") != after
                or after.get("id") != expected["id"]
            ):
                raise ValueError("Foundation successor would alter completed work")
            if not isinstance(old.get("after"), dict) or not _same_known(
                old["after"], expected, old.get("after_unknown", {})
            ):
                raise ValueError(
                    "Foundation successor retained state differs from predecessor intent"
                )
        else:
            if (
                address not in {VM, DELEGATE}
                or old.get("actions") != ["create"]
                or change.get("actions") != ["create"]
                or change.get("before") is not None
                or not isinstance(old.get("after"), dict)
            ):
                raise ValueError("Foundation successor pending work exceeds repair scope")
            expected = repaired_values(address, old["after"])
            pending.append(address)
        if not _same_known(expected, after, old.get("after_unknown", {})):
            raise ValueError("Foundation successor changed an unrelated setting or role operand")
    if set(pending) != {VM, DELEGATE}:
        raise ValueError("Foundation successor requires exactly the two failed pending resources")
    return {
        "state": "review",
        "preserved_managed_count": len(existing),
        "remaining_addresses": sorted(pending),
        "apply_authorized": False,
        "mutation_performed": False,
        "deployment_ready": False,
    }


def group_evidence_valid(review: Mapping[str, object]) -> bool:
    """Distinguish initial absent-group recovery from a bound preserved-group successor."""
    if review.get("predecessor_directory") is None:
        return (
            review.get("application_group_absent") is True
            and not review.get("application_group_preserved")
        ) or (
            review.get("application_group_absent") is False
            and review.get("application_group_preserved") is True
        )
    return (
        review.get("application_group_absent") is False
        and review.get("application_group_preserved") is True
        and all(
            re.fullmatch(r"[0-9a-f]{64}", str(review.get(key, ""))) is not None
            for key in ("predecessor_review_digest", "predecessor_claim_digest")
        )
        and isinstance(review["predecessor_directory"], str)
        and Path(str(review["predecessor_directory"])).is_absolute()
    )


def load_predecessor(
    directory: Path,
    *,
    original_review_digest: str,
    original_claim_digest: str,
    source_commit: str,
    target_binding: str,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    """Verify a single claimed failed recovery without reusing its execution authority."""
    import genesis_runner_image as image
    from genesis_foundation_recovery_apply import _validate_claim

    def read(name: str) -> dict[str, object]:
        return dict(
            load_json_object(
                read_private_bytes(directory / name, max_bytes=64 * 1024 * 1024),
                label="predecessor recovery",
            )
        )

    if (
        not directory.is_absolute()
        or (directory / "recovery-apply-receipt.json").exists()
        or (directory / "recovery-apply-receipt.json").is_symlink()
    ):
        raise ValueError(
            "Foundation successor requires a failed predecessor without success receipt"
        )
    review = read("recovery-review.json")
    if (
        canonical_digest({key: value for key, value in review.items() if key != "review_digest"})
        != review.get("review_digest")
        or review.get("schema_version") != "fdai.foundation-recovery-review.v1"
        or review.get("state") != "review"
        or review.get("predecessor_directory") is not None
        or review.get("application_group_absent") is not True
        or review.get("original_state_unchanged") is not True
        or review.get("original_review_digest") != original_review_digest
        or review.get("original_claim_digest") != original_claim_digest
        or review.get("source_commit") != source_commit
        or review.get("target_binding") != target_binding
        or any(
            review.get(key) is not False
            for key in ("apply_authorized", "mutation_performed", "deployment_ready")
        )
    ):
        raise ValueError("Foundation predecessor review binding is invalid")
    claim = read("recovery-apply-claim.json")
    _validate_claim(claim, review)
    for name, key in (("recovery.tfplan", "plan_digest"), ("show.stdout", "plan_json_digest")):
        if (
            hashlib.sha256(
                read_private_bytes(directory / name, max_bytes=64 * 1024 * 1024)
            ).hexdigest()
            != review[key]
        ):
            raise ValueError("Foundation predecessor saved plan changed")
    if (
        image._execution_tree_digest(directory / "source") != review["configuration_digest"]
        or image._execution_tree_digest(directory / "terraform-data") != review["provider_digest"]
        or canonical_digest(read("recovery-variables.json")) != review["variables_digest"]
    ):
        raise ValueError("Foundation predecessor configuration or provider evidence changed")
    return review, claim, read("show.stdout")


def verify_predecessor_binding(
    review: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object], dict[str, object]] | None:
    """Revalidate the exact retained predecessor referenced by a successor review."""
    if not group_evidence_valid(review):
        raise ValueError("Foundation recovery application ownership evidence is invalid")
    if review.get("predecessor_directory") is None:
        return None
    predecessor = load_predecessor(
        Path(str(review["predecessor_directory"])),
        original_review_digest=str(review["original_review_digest"]),
        original_claim_digest=str(review["original_claim_digest"]),
        source_commit=str(review["source_commit"]),
        target_binding=str(review["target_binding"]),
    )
    if (
        predecessor[0]["review_digest"] != review["predecessor_review_digest"]
        or canonical_digest(predecessor[1]) != review["predecessor_claim_digest"]
        or predecessor[0]["original_lineage_digest"] != review["original_lineage_digest"]
        or predecessor[0]["variables_digest"] != review["variables_digest"]
    ):
        raise ValueError("Foundation successor predecessor reference changed")
    return predecessor

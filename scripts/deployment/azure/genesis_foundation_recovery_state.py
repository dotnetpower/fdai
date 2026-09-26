"""Admit recovered Foundation evidence to the existing private-state migration engine."""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass
from pathlib import Path

import genesis_foundation_state_contract as state_contract
import genesis_runner_enrollment as enrollment_command
import genesis_runner_image as image
from fdai_deployment_cli.contracts import ProvisionProfile, canonical_digest
from fdai_deployment_cli.private_output import read_private_bytes
from fdai_deployment_cli.source_input import SourceDeploymentInput, inspect_source
from genesis_approval import load_genesis_approval
from genesis_approval_prompt import current_actor_digest
from genesis_bastion import validate_known_hosts
from genesis_checks import GenesisChecks
from genesis_foundation_recovery_handoff import (
    RecoveryHandoff,
    load_recovery_evidence,
    verify_original_state,
)
from genesis_foundation_recovery_plan import _json
from genesis_foundation_state_archive import create_foundation_state_archive


@dataclass(frozen=True)
class RecoveryMigration:
    """Carry distinct original-state ownership and current migration-code provenance."""

    original_directory: Path
    directory: Path
    recovered: RecoveryHandoff
    source: SourceDeploymentInput
    enrollment: dict[str, object]
    approval_file: Path | None

    @property
    def foundation(self) -> dict[str, object]:
        """Return in-memory correlation values, not a replacement Foundation receipt."""
        return {
            **self.recovered.foundation_reference,
            "state_digest": self.recovered.receipt["state_digest"],
        }

    @property
    def local_state(self) -> Path:
        """Keep cleanup pinned to the original writer's state, never a copied owner."""
        return (
            self.original_directory
            / "foundation-apply-bundle/source/infra/genesis-foundation/terraform.tfstate"
        )

    def require_approval(self) -> str:
        """Bind a fresh migration effect to its current human and both prior receipts."""
        binding = str(self.recovered.receipt["receipt_digest"])
        approval = load_genesis_approval(
            self.approval_file,
            run_binding=binding,
            source_commit=self.source.commit,
        )
        if (
            approval is None
            or not approval.authorizes(
                "foundation-state",
                foundation_receipt_digest=binding,
                enrollment_receipt_digest=str(self.enrollment["receipt_digest"]),
            )
            or approval.actor_digest != current_actor_digest(binding)
        ):
            raise ValueError(
                "recovered Foundation state migration requires current exact human approval"
            )
        return approval.actor_digest

    def verify_configuration(self) -> None:
        """Require the exact recovered configuration, provider packages and variables."""
        self.source.reverify()
        review = _json(self.directory / "recovery-review.json")
        digest = review.pop("review_digest", None)
        if (
            canonical_digest(review) != digest
            or digest != self.recovered.receipt["review_digest"]
            or image._execution_tree_digest(self.directory / "source")
            != review["configuration_digest"]
            or image._execution_tree_digest(self.directory / "terraform-data")
            != review["provider_digest"]
            or canonical_digest(_json(self.directory / "recovery-variables.json"))
            != review["variables_digest"]
        ):
            raise ValueError("recovered Foundation state migration inputs changed")

    def prepare_archive(self, archive: Path) -> dict[str, object]:
        """Build a bounded transient archive without modifying either original input."""
        self.verify_configuration()
        verify_original_state(self.original_directory, self.directory, self.recovered)
        result = create_foundation_state_archive(
            terraform_root=self.directory / "source/infra/genesis-foundation",
            provider_mirror=self.directory / "terraform-data/providers",
            variables_file=self.directory / "recovery-variables.json",
            destination=archive,
            source_commit=str(self.recovered.receipt["source_commit"]),
            expected_state_digest=str(self.recovered.receipt["state_digest"]),
            original_state=self.local_state,
        )
        self.verify_configuration()
        return result

    def validate_record(self, record: dict[str, object]) -> None:
        """Never resume a migration claim or receipt under different execution source."""
        if (
            record.get("migration_source_commit") != self.source.commit
            or record.get("foundation_evidence_schema") != "fdai.foundation-recovery-receipt.v1"
        ):
            raise ValueError("recovered Foundation state migration provenance differs")

    def validate_claim_record(self, record: dict[str, object]) -> str:
        """Preserve a prior claim while returning its independently verified source."""
        source_commit = record.get("migration_source_commit")
        if (
            not isinstance(source_commit, str)
            or len(source_commit) != 40
            or any(character not in "0123456789abcdef" for character in source_commit)
            or record.get("foundation_evidence_schema") != "fdai.foundation-recovery-receipt.v1"
        ):
            raise ValueError("recovered Foundation state migration claim provenance differs")
        return source_commit


def prepare_recovery_migration(
    args: argparse.Namespace,
    *,
    original_directory: Path,
    root: Path,
    profile: ProvisionProfile,
) -> RecoveryMigration:
    """Validate recovery, enrollment and state ownership under the original execution lock.

    Only an exact retained migration claim plus verified backend authority permits the
    original local state to be absent. The shared engine still independently observes
    the remote backend before returning a completed receipt on verification resume.
    """
    directory = enrollment_command._absolute(args.foundation_recovery_directory)
    if (
        args.source_snapshot is None
        or profile.transport != "manual"
        or profile.environment != "dev"
    ):
        raise ValueError(
            "recovered state migration requires the original source and manual development profile"
        )
    recovered = load_recovery_evidence(
        original_directory=original_directory,
        recovery_directory=directory,
        source_snapshot=enrollment_command._absolute(args.source_snapshot),
        expected_digest=args.expected_foundation_receipt_digest,
        target_binding=profile.target_binding,
    )
    enrolled = state_contract.load_receipt(
        directory / enrollment_command.RECEIPT_NAME,
        schema="fdai.genesis-runner-enrollment-receipt.v1",
        expected_digest=args.expected_enrollment_receipt_digest,
    )
    state_contract.validate_context(
        profile.target_binding, recovered.foundation_reference, enrolled, recovered.handoff
    )
    runner = enrollment_command._object(recovered.handoff["runner"], "recovered runner")
    parallelism = runner.get("parallelism")
    if type(parallelism) is not int or runner.get("execution_transport") != "manual":
        raise ValueError("recovered state migration requires exact manual host enrollment")
    names = enrollment_command._runner_names(str(runner["vm_name"]), parallelism)
    repository_digest = hashlib.sha256(f"manual:{profile.target_binding}".encode()).hexdigest()
    claim = enrollment_command._load_optional_claim(directory / enrollment_command.CLAIM_NAME)
    if (
        claim is None
        or enrolled.get("foundation_evidence_schema") != "fdai.foundation-recovery-receipt.v1"
    ):
        raise ValueError("recovered state migration requires its retained enrollment claim")
    enrollment_command._validate_claim_context(
        claim, recovered.foundation_reference, repository_digest, names
    )
    known_hosts = directory / enrollment_command.KNOWN_HOSTS_NAME
    validate_known_hosts(known_hosts)
    enrollment_command._validate_receipt_context(
        enrolled,
        recovered.foundation_reference,
        repository_digest,
        names,
        claim=claim,
        host_key_digest=hashlib.sha256(
            read_private_bytes(known_hosts, max_bytes=1_048_576)
        ).hexdigest(),
        toolchain_digest=str(runner["toolchain_digest"]),
        manual=True,
    )
    if claim.get("enrollment_source_commit") != enrolled.get("enrollment_source_commit"):
        raise ValueError("recovered state migration enrollment source differs")
    source = inspect_source(root)
    checks = GenesisChecks(root)
    context = RecoveryMigration(
        original_directory, directory, recovered, source, enrolled, args.recovery_approval_file
    )
    state_claim = state_contract.load_claim(directory / "foundation-state-handoff-claim.json")
    migration_claim_source = (
        context.validate_claim_record(state_claim) if state_claim is not None else None
    )
    source_commits = {
        source.commit,
        str(recovered.receipt["execution_source_commit"]),
        str(enrolled.get("enrollment_source_commit")),
    }
    if migration_claim_source is not None:
        source_commits.add(migration_claim_source)
    for commit in source_commits:
        checks.verify_source(source_commit=commit, repository=args.repository, apply=True)
    context.verify_configuration()
    authority = state_contract.load_authority(directory / "foundation-state-authority.json")
    if authority is None:
        verify_original_state(original_directory, directory, recovered)
    else:
        if state_claim is None:
            raise ValueError("recovered state authority lacks its original migration claim")
        backend_key = str(
            enrollment_command._object(recovered.handoff["state"], "recovered backend")[
                "foundation_key"
            ]
        )
        work_id = canonical_digest(
            {
                "foundation_receipt_digest": recovered.receipt["receipt_digest"],
                "enrollment_receipt_digest": enrolled["receipt_digest"],
                "backend_key_digest": hashlib.sha256(backend_key.encode()).hexdigest(),
            }
        )
        state_contract.validate_claim(state_claim, context.foundation, enrolled, work_id)
        state_contract.validate_authority(
            authority, context.foundation, enrolled, state_claim, work_id
        )
        if (
            authority.get("state") != "verified"
            or authority.get("zero_change_verified") is not True
        ):
            raise ValueError("recovered state authority does not prove the original state")
        if context.local_state.exists() or context.local_state.is_symlink():
            verify_original_state(original_directory, directory, recovered)
    if args.approve:
        context.require_approval()
    return context

"""Production construction of current scoped-duty readers and sealed request materialization.

Responsibility: Bind H10's configured catalog, current people, and independent review readers.
Boundary: No provider query occurs during construction; no global duty map or IAM is changed.
Authority and state: Core owns scoped cases under human_assignment through fixed-owner seals.
Dependencies: Shared contracts, same-venue StateStore, and the existing read workload identity.
Deployment: Identical Core package binding locally and deployed; absent catalog stays unavailable.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import yaml

from fdai.core.human_assignment.request_intake import AssignmentRequestIntake
from fdai.core.human_assignment.scoped_duties import ScopedDutyPolicy
from fdai.core.human_assignment.scoped_duty_case_service import ScopedDutyCaseService
from fdai.core.human_assignment.scoped_duty_ownership import ScopedDutyOwnership
from fdai.core.human_assignment.scoped_duty_planning import ScopedDutyPlanner
from fdai.core.human_assignment.scoped_duty_requests import ScopedDutyRequestProcessor
from fdai.core.rbac.resolver import GroupMapping
from fdai.core.rbac.roles import Role
from fdai.delivery.identity.entra_directory import EntraHumanIdentityDirectory
from fdai.delivery.identity.scoped_duty_catalog import FileScopedDutyCatalog
from fdai.delivery.identity.scoped_duty_directory import EntraDutySubjectResolver
from fdai.delivery.identity.scoped_duty_merge import GitHubScopedDutyMergeReader
from fdai.delivery.identity.scoped_duty_owners import CurrentScopedDutyOwners
from fdai.runtime.github_auth import build_github_token_provider, github_credentials_configured
from fdai.runtime.scoped_duty_projection import ScopedDutyProjectionPublisher
from fdai.shared.providers.remediation_pr import RemediationPrPublisher
from fdai.shared.providers.resource_lock import ResourceLock
from fdai.shared.providers.workload_identity import WorkloadIdentity

SCOPED_DUTY_CATALOG_ENV = "FDAI_SCOPED_DUTY_CATALOG_PATH"


def build_scoped_duty_processor(
    *,
    intake: AssignmentRequestIntake,
    environment: Mapping[str, str],
    catalog_root: Path | None,
    http_client: httpx.AsyncClient | None,
    identity: WorkloadIdentity | None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ScopedDutyRequestProcessor | None:
    """Bind real readers; refuse partial configuration instead of using test fakes."""
    location = environment.get(SCOPED_DUTY_CATALOG_ENV, "").strip()
    if not location:
        return None
    if catalog_root is None or http_client is None or identity is None:
        raise ValueError("scoped duty catalog requires the Core read identity and catalog bindings")
    catalog = FileScopedDutyCatalog(Path(location))
    catalog.validate()
    mapping = GroupMapping.from_config(
        yaml.safe_load(
            (catalog_root.parent / "config/rbac-groups.yaml").read_text(encoding="utf-8")
        ),
        environ=environment,
    )
    owner_groups = {
        role.value: group for group, role in mapping.as_dict().items() if role is Role.OWNER
    }
    policy = ScopedDutyPolicy(timedelta(minutes=5), 5.0, 120.0)
    subjects = EntraDutySubjectResolver(
        http_client,
        identity,
        catalog,
        clock,
        policy.max_resolution_age,
        policy.read_timeout_seconds,
    )
    owners = CurrentScopedDutyOwners(
        subjects=subjects,
        directory=EntraHumanIdentityDirectory(
            http_client, identity, max_attempts=1, roster_cache_seconds=0
        ),
        role_group_ids=owner_groups,
        clock=clock,
        timeout_seconds=policy.read_timeout_seconds,
    )
    return ScopedDutyRequestProcessor(
        intake=intake,
        cases=ScopedDutyCaseService(
            intake.store, ScopedDutyPlanner(subjects, catalog, clock, policy), owners, clock
        ),
    )


def build_scoped_duty_projection(
    *,
    processor: ScopedDutyRequestProcessor | None,
    environment: Mapping[str, str],
    http_client: httpx.AsyncClient | None,
    publisher: RemediationPrPublisher | None,
    locks: ResourceLock,
) -> ScopedDutyProjectionPublisher | None:
    """Bind reviewed delivery and current merge reads only with actual GitHub credentials.

    Missing GitHub dependencies leave scoped requests reviewable but their artifact
    consumption unavailable. No recording publisher or synthetic merge reader is bound.
    """
    if processor is None:
        return None
    catalog = processor.cases.planner.scopes
    if not isinstance(catalog, FileScopedDutyCatalog):
        raise ValueError("scoped artifact projection requires its configured current catalog")
    if publisher is None or not github_credentials_configured(environment):
        return ScopedDutyProjectionPublisher(cases=processor.cases, catalog=catalog)
    if http_client is None or not locks.distributed:
        raise ValueError("scoped artifact delivery requires HTTP and a distributed target lock")
    owner = environment.get("FDAI_GITOPS_OWNER", "").strip()
    repo = environment.get("FDAI_GITOPS_REPO", "").strip()
    tokens = build_github_token_provider(environment, http_client=http_client, repository=repo)
    if tokens is None:
        raise ValueError("scoped artifact current merge reader is unavailable")
    return ScopedDutyProjectionPublisher(
        cases=processor.cases,
        ownership=ScopedDutyOwnership(
            processor.cases,
            publisher,
            locks,
            GitHubScopedDutyMergeReader(
                http_client,
                tokens,
                owner + "/" + repo,
                environment.get("FDAI_GITOPS_DEFAULT_BRANCH", "main").strip(),
                processor.cases.clock,
            ),
        ),
        catalog=catalog,
    )


__all__ = ["SCOPED_DUTY_CATALOG_ENV", "build_scoped_duty_processor", "build_scoped_duty_projection"]

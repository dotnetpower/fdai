"""Requests the Hub refuses. Never a database or programming fault."""

from __future__ import annotations

from fdai_lifecycle_hub.enrollment import ProofFailure


class HubStoreError(Exception):
    """A request the Hub data model refuses."""


class UnknownInstallationError(HubStoreError, LookupError):
    pass


class InstallationExistsError(HubStoreError):
    pass


class UnknownPlanError(HubStoreError, LookupError):
    pass


class ReportConflictError(HubStoreError):
    pass


class PlanDigestMismatchError(HubStoreError):
    pass


class ConcurrentWriteError(HubStoreError):
    """Another writer committed first, for example the next audit sequence. Retry."""


class EnrollmentProofError(HubStoreError):
    def __init__(self, failure: ProofFailure) -> None:
        super().__init__(failure)
        self.failure = failure


class NotEnrolledError(HubStoreError):
    """The installation isn't enrolled, so the Hub neither plans for it nor changes it."""


class NotPendingError(HubStoreError):
    """Only a pending enrollment can be approved or rejected."""


class InstallationKeyMismatchError(HubStoreError):
    """The approver named another installation key than the one that requested enrollment."""


class UnknownEntityError(HubStoreError, LookupError):
    pass


class EntityManagedError(HubStoreError):
    """A managed Entity's ownership evidence can't be replaced."""


class EntityNotReportedError(HubStoreError):
    """The latest reported state lacks the Entity, so its settings can't be checked."""


class EntitySettingsRejectedError(HubStoreError):
    """The shared configuration resolver refused the settings for the Entity's running Release."""


class OwnershipUnprovenError(HubStoreError):
    """Only an Entity with proven ownership can have settings."""

"""Requests the Hub refuses. Never a database or programming fault."""

from __future__ import annotations


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

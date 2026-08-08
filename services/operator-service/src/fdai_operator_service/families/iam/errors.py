"""Stable service-local failures rendered by the IAM HTTP boundary."""


class IamFamilyError(RuntimeError):
    """Base failure for an injected IAM family dependency."""

    status_code = 400


class IamPermissionError(IamFamilyError):
    """The authenticated principal lacks the required server-owned authority."""

    status_code = 403


class IamConflictError(IamFamilyError):
    """A revision or idempotency fence rejected a conflicting request."""

    status_code = 409


class IamNotFoundError(IamFamilyError):
    """The requested durable record does not exist."""

    status_code = 404


class IamUnavailableError(IamFamilyError):
    """An authoritative dependency is absent or could not be verified."""

    status_code = 503


__all__ = [
    "IamConflictError",
    "IamFamilyError",
    "IamNotFoundError",
    "IamPermissionError",
    "IamUnavailableError",
]

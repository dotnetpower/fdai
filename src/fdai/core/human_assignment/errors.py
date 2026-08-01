"""Assignment-case error taxonomy shared by policy and persistence layers."""


class AssignmentServiceError(ValueError):
    """Base error for assignment commands rejected by the service."""


class AssignmentConflictError(AssignmentServiceError):
    """Raised when an idempotency identity is reused for different intent."""


class AssignmentPermissionError(PermissionError):
    """Raised when a principal lacks assignment command authority."""


__all__ = [
    "AssignmentConflictError",
    "AssignmentPermissionError",
    "AssignmentServiceError",
]

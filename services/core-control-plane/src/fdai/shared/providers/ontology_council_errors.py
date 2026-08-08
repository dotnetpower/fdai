"""Content-free provider failures understood by ontology council orchestration."""


class CouncilModelError(RuntimeError):
    """Base error whose message is never persisted by council orchestration."""


class CouncilBudgetExceededError(CouncilModelError):
    """The configured provider budget was exhausted before voting."""


class CouncilContextGapError(CouncilModelError):
    """The provider could not interpret the bounded claim packet context."""


__all__ = [
    "CouncilBudgetExceededError",
    "CouncilContextGapError",
    "CouncilModelError",
]

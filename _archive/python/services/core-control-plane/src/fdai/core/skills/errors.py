"""Shared fail-closed errors for runtime skill lifecycle operations."""


class SkillCatalogError(ValueError):
    """Skill lifecycle or read validation failed closed."""


__all__ = ["SkillCatalogError"]

"""Expose shared refreshable GitHub authentication at the Core composition boundary."""

from fdai_github_app_auth import build_github_token_provider, github_credentials_configured

__all__ = ["build_github_token_provider", "github_credentials_configured"]

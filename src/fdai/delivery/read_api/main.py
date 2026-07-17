"""Stable public facade for the console read API app factory."""

from fdai.delivery.read_api.app.config import ReadApiConfig
from fdai.delivery.read_api.app.factory import build_app

__all__ = ["ReadApiConfig", "build_app"]

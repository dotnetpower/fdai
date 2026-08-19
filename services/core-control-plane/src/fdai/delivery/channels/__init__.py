"""Pure conversation-channel presentation adapters without transport bindings."""

from .artifact import normalize_channel_presentation
from .slack import SLACK_PRESENTATION_CAPABILITIES, SlackPresentationRenderer
from .teams import TEAMS_PRESENTATION_CAPABILITIES, TeamsPresentationRenderer

__all__ = [
    "SLACK_PRESENTATION_CAPABILITIES",
    "TEAMS_PRESENTATION_CAPABILITIES",
    "SlackPresentationRenderer",
    "TeamsPresentationRenderer",
    "normalize_channel_presentation",
]

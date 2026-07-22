from __future__ import annotations

import pytest

from fdai.delivery.channels.production_attachments import (
    ProductionAttachmentConfig,
    ProductionAttachmentConfigError,
)


def test_attachment_config_is_disabled_by_default() -> None:
    assert ProductionAttachmentConfig.from_env({}) is None


def test_attachment_config_requires_governed_collection_fields() -> None:
    with pytest.raises(ProductionAttachmentConfigError, match="COLLECTION"):
        ProductionAttachmentConfig.from_env({"FDAI_CHANNEL_ATTACHMENTS_ENABLED": "1"})


def test_attachment_config_parses_bounded_channel_policy() -> None:
    config = ProductionAttachmentConfig.from_env(
        {
            "FDAI_CHANNEL_ATTACHMENTS_ENABLED": "1",
            "FDAI_CHANNEL_ATTACHMENT_COLLECTION": "channel-evidence",
            "FDAI_CHANNEL_ATTACHMENT_ACCESS_REF": "acl-channel-evidence",
            "FDAI_CHANNEL_ATTACHMENT_READER_GROUPS": "group-a,group-b,group-a",
            "FDAI_CHANNEL_ATTACHMENT_RETENTION_POLICY": "retention-v1",
            "FDAI_SLACK_FILE_HOSTS": "files.slack.com",
            "FDAI_TEAMS_ATTACHMENT_HOSTS": "attachments.example.com",
            "FDAI_TEAMS_ATTACHMENT_AUDIENCES": "api://attachments.example.com",
        }
    )

    assert config is not None
    assert config.reader_groups == ("group-a", "group-b")
    assert config.slack_allowed_hosts == ("files.slack.com",)
    assert config.teams_allowed_hosts == ("attachments.example.com",)
    assert config.teams_allowed_audiences == ("api://attachments.example.com",)


@pytest.mark.parametrize("timeout", ("nan", "inf"))
def test_attachment_config_rejects_nonfinite_timeout(timeout: str) -> None:
    with pytest.raises(ProductionAttachmentConfigError, match="positive"):
        ProductionAttachmentConfig.from_env(
            {
                "FDAI_CHANNEL_ATTACHMENTS_ENABLED": "1",
                "FDAI_CHANNEL_ATTACHMENT_COLLECTION": "channel-evidence",
                "FDAI_CHANNEL_ATTACHMENT_ACCESS_REF": "acl-channel-evidence",
                "FDAI_CHANNEL_ATTACHMENT_RETENTION_POLICY": "retention-v1",
                "FDAI_CHANNEL_ATTACHMENT_TIMEOUT_SECONDS": timeout,
            }
        )

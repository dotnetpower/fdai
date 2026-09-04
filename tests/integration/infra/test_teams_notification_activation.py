"""Terraform contracts for A2/A4 Teams activation and receipt transport.

These are static source assertions, not a deployment. They prove that
activation is an explicit deployment input, that the control plane receives
only read authority on the endpoint secret, and that the receipt topic is
provisioned with sender authority on the Operator side alone.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_PLATFORM = (_ROOT / "infra/main.tf").read_text(encoding="utf-8")
_PLATFORM_VARS = (_ROOT / "infra/variables.tf").read_text(encoding="utf-8")
_CORE_ROOT_VARS = (_ROOT / "infra/services/core-control-plane/variables.tf").read_text(
    encoding="utf-8"
)
_CORE_MODULE = (
    _ROOT / "infra/services/core-control-plane/modules/core-control-plane/main.tf"
).read_text(encoding="utf-8")
_OPERATOR_MODULE = (_ROOT / "infra/modules/operator-api/container-app/main.tf").read_text(
    encoding="utf-8"
)
_SPLIT_OPERATOR_ROOT = (_ROOT / "infra/services/operator-service/main.tf").read_text(
    encoding="utf-8"
)
_SPLIT_OPERATOR_VARS = (_ROOT / "infra/services/operator-service/variables.tf").read_text(
    encoding="utf-8"
)
_SPLIT_OPERATOR_MODULE = (
    _ROOT / "infra/services/operator-service/modules/operator-service/main.tf"
).read_text(encoding="utf-8")
_SPLIT_OPERATOR_MODULE_VARS = (
    _ROOT / "infra/services/operator-service/modules/operator-service/variables.tf"
).read_text(encoding="utf-8")
_BOOTSTRAP_TASKS = (
    _ROOT / "services/core-control-plane/src/fdai/runtime/bootstrap_tasks.py"
).read_text(encoding="utf-8")
_BOOTSTRAP_TOPICS = (
    _ROOT / "services/core-control-plane/src/fdai/runtime/bootstrap_topics.py"
).read_text(encoding="utf-8")
_OPERATOR_KAFKA = (
    _ROOT / "services/operator-service/src/fdai_operator_service/adapters/semantic_kafka.py"
).read_text(encoding="utf-8")

_RECEIPT_TOPIC = "fdai.notifications.delivery-receipts"


def test_receipt_topic_is_multiplexed_without_consuming_an_event_hub_entity() -> None:
    auxiliary = re.search(
        r"event_auxiliary_topics\s*=\s*\[(?P<items>.*?)\]",
        _PLATFORM,
        re.DOTALL,
    )
    assert auxiliary is not None
    assert f'"{_RECEIPT_TOPIC}"' not in auxiliary.group("items")
    assert "NOTIFICATION_DELIVERY_RECEIPT_TOPIC" in _BOOTSTRAP_TOPICS
    direct_topics = re.search(
        r"direct_topics\s*=\s*\{(?P<items>.*?)\}",
        _OPERATOR_KAFKA,
        re.DOTALL,
    )
    assert direct_topics is not None
    assert "notification_receipt_topic" not in direct_topics.group("items")


def test_core_consumes_receipts_from_the_primary_event_bus() -> None:
    receipt_consumer = re.search(
        r"hooks[.]consume_notification_receipts[(](?P<body>.*?)[)]",
        _BOOTSTRAP_TASKS,
        re.DOTALL,
    )
    assert receipt_consumer is not None
    assert "bus=config.bus" in receipt_consumer.group("body")
    assert "operational_bus" not in receipt_consumer.group("body")


def test_only_the_operator_command_identity_sends_receipts() -> None:
    sender = re.search(
        r'resource "azurerm_role_assignment" "command_api_eventhubs_sender" \{(?P<body>.*?)\n\}',
        _PLATFORM,
        re.DOTALL,
    )
    assert sender is not None
    assert _RECEIPT_TOPIC not in sender.group("body")
    assert '"fdai.pantheon.objects"' in sender.group("body")
    assert "Azure Event Hubs Data Sender" in sender.group("body")


def test_core_reads_the_endpoint_secret_and_never_writes_it() -> None:
    reader = re.search(
        r'resource "azurerm_role_assignment" "core_teams_notification_secret_reader" '
        r"\{(?P<body>.*?)\n\}",
        _PLATFORM,
        re.DOTALL,
    )
    assert reader is not None
    body = reader.group("body")
    assert 'role_definition_name = "Key Vault Secrets User"' in body
    assert "var.enable_teams_notification_delivery" in body
    assert "azurerm_key_vault_secret.teams_workflow_endpoint[0].resource_versionless_id" in body

    officer = re.search(
        r'resource "azurerm_role_assignment" "teams_workflow_binding_secret_officer" '
        r"\{(?P<body>.*?)\n\}",
        _PLATFORM,
        re.DOTALL,
    )
    assert officer is not None
    assert "module.teams_workflow_binding_identity" in officer.group("body")


def test_activation_is_an_explicit_input_that_defaults_to_disabled() -> None:
    assert 'variable "enable_teams_notification_delivery"' in _PLATFORM_VARS
    activation = re.search(
        r'variable "enable_teams_notification_delivery" \{(?P<body>.*?)\n\}',
        _PLATFORM_VARS,
        re.DOTALL,
    )
    assert activation is not None
    assert "default     = false" in activation.group("body")

    binding = re.search(
        r'variable "teams_notification_binding" \{(?P<body>.*?)\n\}\n',
        _CORE_ROOT_VARS,
        re.DOTALL,
    )
    assert binding is not None
    body = binding.group("body")
    assert "enabled            = optional(bool, false)" in body
    # A Teams Workflows binding may never claim an approval trust tier.
    assert "a2_operational_alert" in body
    assert "a4_digest" in body
    assert "a1_hil_approval" not in body


def test_core_binds_the_endpoint_secret_only_when_activation_is_requested() -> None:
    assert "local.teams_notification_enabled" in _CORE_MODULE
    assert "key_vault_secret_id = var.teams_notification_binding.endpoint_secret_id" in _CORE_MODULE
    assert (
        "{ name = local.teams_notification_endpoint_env, "
        'secret_name = "teams-notification-endpoint" }' in _CORE_MODULE
    )
    assert '{ name = "FDAI_NOTIFICATION_RECEIPT_TOPIC"' in _CORE_MODULE


def test_operator_receives_the_receipt_secret_and_topic() -> None:
    assert 'name                = "notification-receipt-secret"' in _OPERATOR_MODULE
    assert 'name        = "FDAI_NOTIFICATION_RECEIPT_SECRET"' in _OPERATOR_MODULE
    assert 'name  = "FDAI_NOTIFICATION_RECEIPT_TOPIC"' in _OPERATOR_MODULE
    assert 'notification_receipt_topic         = "fdai.notifications.delivery-receipts"' in (
        _PLATFORM
    )
    assert (
        "notification_receipt_topic         = module.event_bus.auxiliary_topic_ids" not in _PLATFORM
    )


def test_split_operator_receives_the_receipt_secret_and_topic() -> None:
    assert 'variable "notification_receipt_secret_id"' in _SPLIT_OPERATOR_VARS
    assert "notification_receipt_secret_id = var.notification_receipt_secret_id" in (
        _SPLIT_OPERATOR_ROOT
    )
    assert (
        "notification_receipts          = optional(string, "
        '"fdai.notifications.delivery-receipts")' in _SPLIT_OPERATOR_MODULE_VARS
    )
    assert 'name                = "notification-receipt-secret"' in _SPLIT_OPERATOR_MODULE
    assert 'name = "FDAI_NOTIFICATION_RECEIPT_SECRET"' in _SPLIT_OPERATOR_MODULE
    assert 'name = "FDAI_NOTIFICATION_RECEIPT_TOPIC"' in _SPLIT_OPERATOR_MODULE


def test_no_endpoint_or_receipt_secret_value_is_committed() -> None:
    for source in (_PLATFORM, _PLATFORM_VARS, _CORE_MODULE, _OPERATOR_MODULE):
        assert "powerplatform.com" not in source
        assert "sig=" not in source

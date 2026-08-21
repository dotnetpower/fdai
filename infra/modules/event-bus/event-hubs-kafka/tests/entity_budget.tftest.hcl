mock_provider "azurerm" {}

run "standard_accepts_ten_entities" {
  command = plan

  variables {
    name                = "evhns-fdai-example"
    location            = "example-region"
    resource_group_name = "rg-example"
    topics = [
      "fdai.change.events",
      "fdai.dr.events",
      "fdai.finops.events",
      "fdai.pantheon.objects",
    ]
    auxiliary_topics = ["fdai.hil.decisions", "fdai.pipeline.stages"]
  }
}

run "standard_rejects_more_than_ten_entities" {
  command = plan

  variables {
    name                = "evhns-fdai-example"
    location            = "example-region"
    resource_group_name = "rg-example"
    topics = [
      "fdai.change.events",
      "fdai.dr.events",
      "fdai.finops.events",
      "fdai.pantheon.objects",
      "operator.semantic-turn.requests",
    ]
    auxiliary_topics = ["fdai.hil.decisions", "fdai.pipeline.stages"]
  }

  expect_failures = [azurerm_eventhub_namespace.primary]
}

run "primary_rejects_legacy_product_prefix" {
  command = plan

  variables {
    name                = "evhns-fdai-example"
    location            = "example-region"
    resource_group_name = "rg-example"
    topics              = ["aw.change.events"]
  }

  expect_failures = [var.topics]
}

run "auxiliary_rejects_legacy_product_prefix" {
  command = plan

  variables {
    name                = "evhns-fdai-example"
    location            = "example-region"
    resource_group_name = "rg-example"
    topics              = ["fdai.change.events"]
    auxiliary_topics    = ["aw.pipeline.stages"]
  }

  expect_failures = [var.auxiliary_topics]
}

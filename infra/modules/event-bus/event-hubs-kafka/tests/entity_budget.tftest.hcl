mock_provider "azurerm" {}

run "standard_accepts_ten_entities" {
  command = plan

  variables {
    name                = "evhns-fdai-example"
    location            = "example-region"
    resource_group_name = "rg-example"
    topics = [
      "aw.change.events",
      "aw.dr.events",
      "aw.finops.events",
      "aw.pantheon.objects",
    ]
    auxiliary_topics = ["aw.hil.decisions", "aw.pipeline.stages"]
  }
}

run "standard_rejects_more_than_ten_entities" {
  command = plan

  variables {
    name                = "evhns-fdai-example"
    location            = "example-region"
    resource_group_name = "rg-example"
    topics = [
      "aw.change.events",
      "aw.dr.events",
      "aw.finops.events",
      "aw.pantheon.objects",
      "operator.semantic-turn.requests",
    ]
    auxiliary_topics = ["aw.hil.decisions", "aw.pipeline.stages"]
  }

  expect_failures = [azurerm_eventhub_namespace.primary]
}

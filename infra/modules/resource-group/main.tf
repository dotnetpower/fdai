resource "terraform_data" "ownership" {
  input = var.reference_existing ? "reference" : "managed"

  lifecycle {
    ignore_changes = [input]
    postcondition {
      condition     = self.input == (var.reference_existing ? "reference" : "managed")
      error_message = "Resource-group ownership cannot change without a separately reviewed state handoff."
    }
  }
}

resource "azurerm_resource_group" "primary" {
  count = var.reference_existing ? 0 : 1

  name     = var.name
  location = var.location
  tags     = var.tags

  depends_on = [terraform_data.ownership]
}

moved {
  from = azurerm_resource_group.primary
  to   = azurerm_resource_group.primary[0]
}

data "azurerm_resource_group" "foundation" {
  count = var.reference_existing ? 1 : 0
  name  = var.name

  depends_on = [terraform_data.ownership]

  lifecycle {
    postcondition {
      condition = (
        self.location == var.location &&
        try(self.tags["fdai:foundation-context"], "") == var.foundation_context_digest
      )
      error_message = "The referenced group must match the approved foundation context and region."
    }
  }
}

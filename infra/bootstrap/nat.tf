# -----------------------------------------------------------------------
# Runner subnet outbound - NAT gateway (explicit, durable egress).
#
# The runner VM has no public IP and `snet-runner` was originally created
# relying on Azure "default outbound access". That implicit egress is being
# retired by Azure: after a VM deallocate/start cycle the subnet lost all
# outbound internet, so the self-hosted runner could no longer reach GitHub
# and `terraform` could no longer reach `management.azure.com` (ARM) or
# `login.microsoftonline.com` (AAD) - the state blob stayed reachable over its
# private endpoint, but every public control-plane call timed out.
#
# A NAT gateway is the supported, stable replacement for default outbound. It
# provides SNAT egress for the whole subnet through one static public IP,
# keeps the VM itself with no public IP (no inbound exposure), and survives
# deallocate/start cycles. Attached via the association resource so it composes
# without editing the `azurerm_subnet.runner` block.
#
# A closed network sets `enable_public_egress = false`: the tenant supplies its
# own approved path to the management and identity planes, the host is a
# jumpbox rather than a GitHub-registered runner, and this layer creates no
# public IP at all.
# -----------------------------------------------------------------------

resource "azurerm_public_ip" "nat" {
  count               = var.enable_public_egress ? 1 : 0
  name                = "pip-nat-${local.suffix}"
  location            = var.region
  resource_group_name = azurerm_resource_group.ops.name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.tags
}

resource "azurerm_nat_gateway" "runner" {
  count                   = var.enable_public_egress ? 1 : 0
  name                    = "natgw-${local.suffix}"
  location                = var.region
  resource_group_name     = azurerm_resource_group.ops.name
  sku_name                = "Standard"
  idle_timeout_in_minutes = 4
  tags                    = local.tags
}

resource "azurerm_nat_gateway_public_ip_association" "nat" {
  count                = var.enable_public_egress ? 1 : 0
  nat_gateway_id       = azurerm_nat_gateway.runner[0].id
  public_ip_address_id = azurerm_public_ip.nat[0].id
}

resource "azurerm_subnet_nat_gateway_association" "runner" {
  count          = var.enable_public_egress ? 1 : 0
  subnet_id      = azurerm_subnet.runner.id
  nat_gateway_id = azurerm_nat_gateway.runner[0].id
}

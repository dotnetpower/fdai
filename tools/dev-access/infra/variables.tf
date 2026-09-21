variable "region" {
  description = "Azure region for the isolated development-access resources."
  type        = string
}

variable "region_short" {
  description = "Short region token used in resource names."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]{2,8}$", var.region_short))
    error_message = "region_short must contain 2-8 lowercase ASCII letters or digits."
  }
}

variable "entra_audience" {
  description = "Microsoft-registered Azure VPN Client audience for the active Azure cloud."
  type        = string

  validation {
    condition = (
      can(regex("^[0-9a-fA-F-]{36}$", var.entra_audience)) &&
      var.entra_audience != "00000000-0000-0000-0000-000000000000"
    )
    error_message = "entra_audience must be the non-placeholder GUID supplied by the Microsoft P2S documentation."
  }
}

variable "fdai_vnet" {
  description = "Existing FDAI development VNet connected only by removable peering."
  type = object({
    id                  = string
    name                = string
    resource_group_name = string
  })

  validation {
    condition     = startswith(lower(var.fdai_vnet.id), "/subscriptions/")
    error_message = "fdai_vnet.id must be a complete Azure resource ID."
  }
}

variable "additional_vnets" {
  description = "Additional private VNets that require direct P2S reachability. Map keys are stable peering-name tokens."
  type = map(object({
    id                  = string
    name                = string
    resource_group_name = string
    address_spaces      = set(string)
  }))
  default = {}

  validation {
    condition = alltrue([
      for key, vnet in var.additional_vnets :
      can(regex("^[a-z0-9-]{1,40}$", key)) &&
      startswith(lower(vnet.id), "/subscriptions/") &&
      trimspace(vnet.name) != "" &&
      trimspace(vnet.resource_group_name) != "" &&
      length(vnet.address_spaces) > 0 &&
      alltrue([for address_space in vnet.address_spaces : can(cidrhost(address_space, 0))])
    ])
    error_message = "Additional VNet keys must be lowercase link tokens and every VNet must include an ID, name, resource group, and valid address spaces."
  }
}

variable "fdai_private_dns_zones" {
  description = "Existing FDAI Private DNS zones to link to the development-access VNet. Map keys are stable link-name tokens."
  type = map(object({
    name                = string
    resource_group_name = string
  }))

  validation {
    condition = length(var.fdai_private_dns_zones) > 0 && alltrue([
      for key, zone in var.fdai_private_dns_zones : can(regex("^[a-z0-9-]{1,40}$", key)) &&
      trimspace(zone.name) != "" && trimspace(zone.resource_group_name) != ""
    ])
    error_message = "Private DNS zone keys must be lowercase link tokens and every zone must include a name and resource group."
  }
}

variable "dev_access_address_space" {
  description = "Address space for the isolated development-access VNet. It must not overlap FDAI, local LAN, WSL, or the VPN client pool."
  type        = string
  default     = "10.71.0.0/24"

  validation {
    condition     = can(cidrhost(var.dev_access_address_space, 0))
    error_message = "dev_access_address_space must be a valid CIDR."
  }
}

variable "gateway_subnet_prefix" {
  description = "CIDR for the required GatewaySubnet."
  type        = string
  default     = "10.71.0.0/27"

  validation {
    condition     = can(cidrhost(var.gateway_subnet_prefix, 0))
    error_message = "gateway_subnet_prefix must be a valid CIDR."
  }
}

variable "resolver_inbound_subnet_prefix" {
  description = "Dedicated delegated subnet for the Private DNS Resolver inbound endpoint."
  type        = string
  default     = "10.71.0.32/28"

  validation {
    condition     = can(cidrhost(var.resolver_inbound_subnet_prefix, 0))
    error_message = "resolver_inbound_subnet_prefix must be a valid CIDR."
  }
}

variable "vpn_client_address_pool" {
  description = "Address pool assigned to connected P2S clients. It must not overlap any connected network."
  type        = string
  default     = "172.30.250.0/24"

  validation {
    condition     = can(cidrhost(var.vpn_client_address_pool, 0))
    error_message = "vpn_client_address_pool must be a valid CIDR."
  }
}

variable "gateway_sku" {
  description = "Route-based VPN Gateway SKU. Basic is not supported because this stack requires OpenVPN."
  type        = string
  default     = "VpnGw1AZ"

  validation {
    condition     = contains(["VpnGw1AZ", "VpnGw2AZ", "VpnGw3AZ", "VpnGw4AZ", "VpnGw5AZ"], var.gateway_sku)
    error_message = "gateway_sku must be an availability-zone-capable SKU that supports OpenVPN P2S connections."
  }
}

variable "additional_tags" {
  description = "Additional generic tags for the development-access resources."
  type        = map(string)
  default     = {}
}

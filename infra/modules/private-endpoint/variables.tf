variable "name" {
  description = "Private endpoint name, e.g. pe-kv-fdai-dev-krc."
  type        = string
}

variable "location" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "subnet_id" {
  description = "Subnet the private endpoint NIC attaches to (the network module's pe subnet)."
  type        = string
}

variable "vnet_id" {
  description = "VNet the private DNS zone links to for name resolution."
  type        = string
}

variable "target_resource_id" {
  description = "Resource id of the service the PE fronts (e.g. the Key Vault id)."
  type        = string
}

variable "subresource_name" {
  description = "Service subresource / group id (vault | registry | namespace | postgresqlServer | ...)."
  type        = string
}

variable "private_dns_zone_name" {
  description = "privatelink.* DNS zone for the service (e.g. privatelink.vaultcore.azure.net)."
  type        = string
}

variable "extra_vnet_links" {
  description = "Additional VNets to link the private DNS zone to (link_name -> vnet_id). Use this to let a runner in a peered hub VNet resolve the private endpoint (e.g. { ops = <ops_vnet_id> })."
  type        = map(string)
  default     = {}
}

variable "tags" {
  type    = map(string)
  default = {}
}

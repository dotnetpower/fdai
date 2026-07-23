variable "name" {
  description = "Event Hubs namespace name (CAF: evhns-<workload>[-env][-region])."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "resource_group_name" {
  description = "Enclosing resource group."
  type        = string
}

variable "topics" {
  description = "Kafka topics to provision under this namespace. DLQ siblings (<topic>.dlq) are auto-created."
  type        = list(string)
}

variable "auxiliary_topics" {
  description = "Event Hub entities that do not receive a generated DLQ sibling."
  type        = list(string)
  default     = []
}

variable "partition_count" {
  description = "Partition count per topic. Day-zero default 2."
  type        = number
  default     = 2
}

variable "sku" {
  description = "Event Hubs SKU. Standard supports Kafka wire on :9093."
  type        = string
  default     = "Standard"
}

variable "public_network_access_enabled" {
  description = "Whether the Event Hubs namespace accepts public network traffic. Private-networking deployments set false and attach a private endpoint."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags."
  type        = map(string)
  default     = {}
}

variable "name" {
  description = "CAF-compliant name of the design-mocks Static Web App."
  type        = string
}

variable "location" {
  description = "Azure region that supports Static Web Apps."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group that owns the design-mocks Static Web App."
  type        = string
}

variable "tags" {
  description = "Tags applied to the design-mocks Static Web App."
  type        = map(string)
  default     = {}
}

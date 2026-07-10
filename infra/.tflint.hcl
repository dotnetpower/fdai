# tflint config for the FDAI infra. Run: tflint --recursive (from infra/).
# The azurerm ruleset catches provider-specific mistakes (invalid SKUs,
# deprecated args) that `terraform validate` does not.

config {
  call_module_type = "local"
}

plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

plugin "azurerm" {
  enabled = true
  version = "0.28.0"
  source  = "github.com/terraform-linters/tflint-ruleset-azurerm"
}

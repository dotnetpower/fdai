output "console_static_web_app_id" {
  description = "Static Web App resource id used by the bounded Console publisher."
  value       = module.console.static_web_app_id
}

output "console_default_hostname" {
  description = "Azure-provided Static Web App hostname."
  value       = module.console.default_hostname
}

output "console_hostname" {
  description = "Effective Console hostname, including the custom hostname when configured."
  value       = local.console_hostname
}

output "console_origin" {
  description = "Exact HTTPS Console origin for Entra SPA redirect and CORS registration."
  value       = local.console_origin
}

output "console_redirect_uri" {
  description = "Exact Microsoft Entra SPA redirect URI for the Console."
  value       = local.console_origin
}

output "browser_gateway_id" {
  description = "API Management resource id."
  value       = module.browser_gateway.api_management_id
}

output "browser_gateway_name" {
  description = "API Management service name."
  value       = module.browser_gateway.api_management_name
}

output "browser_gateway_url" {
  description = "API Management HTTPS origin."
  value       = module.browser_gateway.gateway_url
}

output "gateway_frontend_tenant_id" {
  description = "Microsoft Entra tenant expected by the APIM JWT policies."
  value       = var.frontend_tenant_id
}

output "gateway_frontend_audience" {
  description = "Operator API client audience expected by the APIM JWT policies."
  value       = var.frontend_audience
}

output "operator_api_base_url" {
  description = "Authenticated Operator API base URL used by the Console."
  value       = module.browser_gateway.operator_url
}

output "ingestion_api_base_url" {
  description = "Authenticated document ingestion API base URL used by the Console."
  value       = module.browser_gateway.ingestion_url
}

output "operator_health_url" {
  description = "Unauthenticated gateway reachability probe for Operator API readiness."
  value       = "${module.browser_gateway.operator_url}/healthz"
}

output "ingestion_health_url" {
  description = "Unauthenticated gateway reachability probe for document ingestion readiness."
  value       = "${module.browser_gateway.ingestion_url}/healthz"
}

output "operator_unauthenticated_probe_url" {
  description = "Operator API URL that must return 401 without an access token."
  value       = "${module.browser_gateway.operator_url}/audit"
}

output "ingestion_unauthenticated_probe_url" {
  description = "Document ingestion URL that must return 401 without an access token."
  value       = "${module.browser_gateway.operator_url}/documents"
}

output "reachability_checks" {
  description = "Exact non-secret bindings required by live Console and gateway reachability verification."
  value = {
    gateway_frontend_tenant_id          = var.frontend_tenant_id
    gateway_frontend_audience           = var.frontend_audience
    console_origin                      = local.console_origin
    console_static_web_app_id           = module.console.static_web_app_id
    operator_health_url                 = "${module.browser_gateway.operator_url}/healthz"
    ingestion_health_url                = "${module.browser_gateway.ingestion_url}/healthz"
    operator_unauthenticated_probe_url  = "${module.browser_gateway.operator_url}/audit"
    ingestion_unauthenticated_probe_url = "${module.browser_gateway.operator_url}/documents"
  }
}

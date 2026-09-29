output "service" {
  description = "Operational evidence verifier deployment outputs."
  value       = module.verifier.service
}

output "identity_principal_id" {
  description = "Dedicated verifier principal id that must differ from every executor-class anchor."
  value       = var.identity.principal_id
}

output "health_contract" {
  description = "Health contract used by post-deploy verification."
  value       = var.health
}

output "internal_ingress" {
  description = "Verifier ingress boundary; external access must stay disabled."
  value       = module.verifier.internal_ingress
}

output "id" { value = module.container_app.id }
output "name" { value = module.container_app.name }
output "fqdn" { value = module.container_app.fqdn }
output "latest_revision_name" { value = module.container_app.latest_revision_name }
output "channel_edge" {
  value = var.channel_edge.enabled ? {
    id                   = module.channel_edge[0].id
    name                 = module.channel_edge[0].name
    fqdn                 = module.channel_edge[0].fqdn
    latest_revision_name = module.channel_edge[0].latest_revision_name
  } : null
}

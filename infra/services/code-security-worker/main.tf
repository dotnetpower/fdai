module "code_security_worker" {
  source = "./modules/code-security-worker"

  name        = var.name
  platform    = var.platform
  image       = var.image
  identity    = var.identity
  database    = var.database
  github      = var.github
  cache       = var.cache
  runtime_env = var.runtime_env
  worker      = var.worker
  resources   = var.resources
  tags        = var.tags
}

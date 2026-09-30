# Terraform module for the Ideation Engine (ADR-0018 §2, retired by ADR-0021).
#
# `biffo plugin install ideation` copies this directory into the instance's
# monorepo at modules/plugins/ideation/ and generates the instantiating module
# block into infra/environments/<env>/plugins.generated.tf (CLI-owned).
#
# This module provisions no resources. The backend Lambda + API Gateway ingress
# went with the move to the shared plugin host (ADR-0021), and the per-plugin
# frontend bucket went with biffo-template#558: the shared host now serves the
# founder UI itself at /api/v1/plugins/ideation/ui/*.

terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

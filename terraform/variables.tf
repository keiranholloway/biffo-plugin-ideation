variable "project_name" {
  description = "The instance's project name (name-prefixes every resource)."
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev/staging/prod)."
  type        = string
}

variable "plugin_name" {
  description = "This plugin's name — the URL segment and the system:<name> principal."
  type        = string
  default     = "ideation"
}

variable "handler" {
  description = "The Lambda handler (the manifest's user_ingress.handler)."
  type        = string
  default     = "ideation.app.handler"
}

variable "runtime" {
  description = "Lambda runtime."
  type        = string
  default     = "python3.13"
}

variable "memory_size" {
  description = "Lambda memory (MB)."
  type        = number
  default     = 512
}

variable "timeout" {
  description = "Lambda timeout (s). Must exceed the chat spine's per-turn timeout."
  type        = number
  default     = 30
}

# --- Core seams (ADR-0009 / ADR-0017) ---------------------------------------

variable "core_api_url" {
  description = "Base URL of the Core API this plugin calls over HTTPS."
  type        = string
}

variable "core_api_execution_arn" {
  description = "Execution ARN of the Core API Gateway, scoping the SigV4 grant to /api/v1/internal/*."
  type        = string
}

# --- Shared Cognito (ADR-0018 §1 — the founder gate verifies the JWT) --------

variable "cognito_user_pool_id" {
  description = "Shared Cognito User Pool id — the SAME pool as the portal."
  type        = string
}

variable "cognito_region" {
  description = "Region of the shared Cognito pool."
  type        = string
}

variable "cognito_client_id" {
  description = "Shared Cognito App Client id — the SAME client as the portal (SSO)."
  type        = string
}

variable "cognito_jwks_json" {
  description = "Baked JWKS for the shared pool (offline verification, no per-cold-start fetch). Optional."
  type        = string
  default     = ""
}

# --- Frontend routing (ADR-0007 / ADR-0018 §2) -------------------------------

variable "cdn_distribution_arn" {
  description = "ARN of the shared CloudFront distribution — the only reader of the frontend bucket."
  type        = string
}

# --- Models -----------------------------------------------------------------

variable "chat_model" {
  description = "Model for the challenger chat turns."
  type        = string
  default     = "anthropic/claude-sonnet-4"
}

variable "analysis_model" {
  description = "Model for the async analyst run."
  type        = string
  default     = "anthropic/claude-opus-4-8"
}

# --- Baseline compute wiring (mirrors the plugin template) -------------------

variable "enable_vpc_access" {
  description = "Whether the Lambda attaches to the VPC (only if it needs private egress)."
  type        = bool
  default     = false
}

variable "vpc_id" {
  description = "VPC id (only when enable_vpc_access)."
  type        = string
  default     = ""
}

variable "private_subnet_ids" {
  description = "Private subnet ids (only when enable_vpc_access)."
  type        = list(string)
  default     = []
}

variable "event_bus_name" {
  description = "Shared event bus name (compute wires the Lambda's DLQ/logging baseline)."
  type        = string
  default     = "default"
}

variable "environment_variables" {
  description = "Extra Lambda environment variables (merged; the plugin's own keys win)."
  type        = map(string)
  default     = {}
}

variable "sqs_kms_key_id" {
  description = "KMS key id for the Lambda DLQ."
  type        = string
  default     = ""
}

variable "cloudwatch_kms_key_id" {
  description = "KMS key id for the Lambda's log group."
  type        = string
  default     = ""
}

variable "tags" {
  description = "Resource tags."
  type        = map(string)
  default     = {}
}

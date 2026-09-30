variable "project_name" {
  description = "The instance's project name (name-prefixes every resource)."
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev/staging/prod)."
  type        = string
}

variable "plugin_name" {
  description = "This plugin's name — the URL segment."
  type        = string
  default     = "ideation"
}

variable "tags" {
  description = "Resource tags."
  type        = map(string)
  default     = {}
}

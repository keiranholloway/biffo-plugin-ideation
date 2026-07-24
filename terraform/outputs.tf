# These outputs are what `biffo plugin install` reads to register the plugin into
# the shared CloudFront: function_url_domain -> cdn's plugin_api_origins (the
# <ideation>/api/* behaviour), frontend_bucket_regional_domain -> cdn's
# sibling_origins (the <ideation>/* frontend behaviour). frontend_bucket_name is
# the deploy target the built web/dist is synced to.

output "function_url_domain" {
  description = "The api ingress origin host (no scheme, no trailing slash) — the plugin_api_origins origin. Now the API Gateway execute-api domain (the ingress moved off a Lambda Function URL — see main.tf)."
  value       = trimsuffix(trimprefix(aws_apigatewayv2_api.ingress.api_endpoint, "https://"), "/")
}

output "frontend_bucket_regional_domain" {
  description = "The frontend bucket's regional domain — the sibling_origins origin."
  value       = aws_s3_bucket.frontend.bucket_regional_domain_name
}

output "frontend_bucket_name" {
  description = "The frontend bucket name — the deploy target for the built web/dist."
  value       = aws_s3_bucket.frontend.id
}

output "function_name" {
  description = "The plugin Lambda's function name."
  value       = module.function.function_name
}

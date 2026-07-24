# Terraform for the Ideation Engine — a USER-FACING plugin (ADR-0018).
#
# `biffo plugin install ideation` copies this directory into the instance's
# monorepo at modules/plugins/ideation/ and generates the instantiating module
# block into infra/environments/<env>/plugins.generated.tf (CLI-owned). The
# relative `../../cloud/aws/*` sources resolve there, against the instance's own
# modules; in the plugin repo this is `terraform fmt`-checked and validated in the
# instance/pipeline.
#
# Unlike the event-driven plugin template, a user-facing module (ADR-0018 §1):
#   - has NO EventBridge subscription — it is reached by a founder over HTTP;
#   - exposes a Lambda Function URL (auth NONE — the Lambda verifies the founder's
#     Cognito JWT itself via require_group), which the shared CloudFront routes at
#     <base>/ideation/api/* (registered into cdn's plugin_api_origins by install);
#   - serves a static frontend from its own S3 bucket, routed at <base>/ideation/*
#     (registered into cdn's sibling_origins by install);
#   - is granted SigV4 access to Core's /api/v1/internal/* (ADR-0009), and its role
#     name yields the logical principal `system:ideation` the owner-scoped tables
#     name (ADR-0017 §5).

terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

locals {
  name_prefix   = "${var.project_name}-${var.environment}"
  function_name = "${local.name_prefix}-plugin-${var.plugin_name}"
}

# The plugin's Lambda — the founder-gated FastAPI+Mangum ingress (ideation.app.handler).
module "function" {
  source = "../../cloud/aws/compute"

  project_name       = var.project_name
  environment        = var.environment
  function_name      = "plugin-${var.plugin_name}"
  handler            = var.handler
  runtime            = var.runtime
  memory_size        = var.memory_size
  timeout            = var.timeout
  enable_vpc_access  = var.enable_vpc_access
  vpc_id             = var.vpc_id
  private_subnet_ids = var.private_subnet_ids
  event_bus_name     = var.event_bus_name

  # No db_credentials_secret_arn (ADR-0002): the plugin reaches Core over HTTPS.
  # The shared-Cognito coordinates let require_group verify the founder's JWT at
  # the edge; the models are the ones IdeationService drives.
  environment_variables = merge(
    {
      BIFFO_CORE_API_URL         = var.core_api_url
      BIFFO_PLUGIN_NAME          = var.plugin_name
      BIFFO_COGNITO_USER_POOL_ID = var.cognito_user_pool_id
      BIFFO_COGNITO_REGION       = var.cognito_region
      BIFFO_COGNITO_CLIENT_ID    = var.cognito_client_id
      BIFFO_COGNITO_JWKS_JSON    = var.cognito_jwks_json
      IDEATION_CHAT_MODEL        = var.chat_model
      IDEATION_ANALYSIS_MODEL    = var.analysis_model
    },
    var.environment_variables,
  )

  sqs_kms_key_id        = var.sqs_kms_key_id
  cloudwatch_kms_key_id = var.cloudwatch_kms_key_id
  tags                  = var.tags
}

# The authenticated ingress (ADR-0018 §1): an HTTP API Gateway in front of the
# Lambda, reached by the shared CloudFront as an ordinary custom origin.
#
# Why API Gateway and not a Lambda Function URL: the account guardrail blocks
# public (NONE-auth) Function URLs, and an OAC-signed (IAM) Function URL cannot
# serve browser requests with a body — CloudFront OAC requires the CLIENT to
# compute the SHA256 of the body and SigV4-sign it (AWS docs: "Lambda doesn't
# support unsigned payloads"), which a browser fetch() cannot do. This API is
# POST-heavy, so a Function URL is a dead end. API Gateway is a public HTTPS
# endpoint (the guardrail allows it — the Core API uses it) and the Lambda
# authenticates every request itself (require_group verifies the shared-Cognito
# founder JWT), so the routes need no API-Gateway authorizer.
resource "aws_apigatewayv2_api" "ingress" {
  name          = "${var.project_name}-${var.environment}-ideation"
  protocol_type = "HTTP"
  description   = "Ideation plugin authenticated ingress (ADR-0018)"
  tags          = var.tags
}

resource "aws_apigatewayv2_integration" "ingress" {
  api_id                 = aws_apigatewayv2_api.ingress.id
  integration_type       = "AWS_PROXY"
  integration_uri        = module.function.function_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 29000
}

# $default route: the founder-JWT gate in the Lambda is the only authorization.
resource "aws_apigatewayv2_route" "ingress" {
  api_id             = aws_apigatewayv2_api.ingress.id
  route_key          = "$default"
  target             = "integrations/${aws_apigatewayv2_integration.ingress.id}"
  authorization_type = "NONE"
}

resource "aws_apigatewayv2_stage" "ingress" {
  api_id      = aws_apigatewayv2_api.ingress.id
  name        = "$default"
  auto_deploy = true
  tags        = var.tags
}

resource "aws_lambda_permission" "ingress" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = module.function.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.ingress.execution_arn}/*/*"
}

# Core API access (ADR-0009): SigV4-signed calls to /api/v1/internal/* only. The
# role name is the logical principal `system:ideation` the owner-scoped tables
# grant (compute names the role <prefix>-plugin-ideation-role).
data "aws_iam_policy_document" "core_api" {
  statement {
    sid       = "InvokeCoreInternalApi"
    effect    = "Allow"
    actions   = ["execute-api:Invoke"]
    resources = ["${var.core_api_execution_arn}/*/*/api/v1/internal/*"]
  }
}

resource "aws_iam_role_policy" "core_api" {
  name   = "${local.function_name}-core-api"
  role   = element(split("/", module.function.role_arn), length(split("/", module.function.role_arn)) - 1)
  policy = data.aws_iam_policy_document.core_api.json
}

# The frontend's own S3 origin (ADR-0007 sibling shape). The built web/dist is
# deployed here; the shared CloudFront reads it (routed at <base>/ideation/* via
# cdn's sibling_origins, registered by install). Access is ONLY through the
# distribution — the bucket itself is fully private.
resource "aws_s3_bucket" "frontend" {
  #checkov:skip=CKV_AWS_18:Static public-app assets served via CloudFront; access logging is the distribution's, not per-bucket.
  #checkov:skip=CKV_AWS_144:Non-critical, rebuildable static assets; cross-region replication unwarranted.
  #checkov:skip=CKV2_AWS_61:Rebuildable static assets; lifecycle expiration not required.
  #checkov:skip=CKV2_AWS_62:Static assets; event notifications not applicable.
  bucket        = "${local.name_prefix}-plugin-${var.plugin_name}-web"
  force_destroy = true
  tags          = var.tags
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Read access for the shared CloudFront distribution only (its OAC signs the
# request; the condition ties the grant to this exact distribution).
data "aws_iam_policy_document" "frontend" {
  statement {
    sid       = "AllowSharedCloudFrontRead"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.frontend.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [var.cdn_distribution_arn]
    }
  }
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  policy = data.aws_iam_policy_document.frontend.json
}

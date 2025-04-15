# Global
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "aws_vpc" "vpc" {
  id = var.vpc_id
}

data "aws_iam_policy_document" "ecs_trust_policy" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# combine all policy docs defined below for the task_role
data "aws_iam_policy_document" "prefect_ecs_task_role_policy_doc" {
  source_policy_documents = [
    data.aws_iam_policy_document.prefect_s3_policy.json,
    data.aws_iam_policy_document.prefect_s3_full_policy.json,
    data.aws_iam_policy_document.prefect_parameter_policy.json,
    data.aws_iam_policy_document.prefect_secrets_policy.json,
    data.aws_iam_policy_document.prefect_cloudwatch_policy.json,
  ]
}

# Prefect ECS S3
# data "aws_iam_policy_document" "prefect_s3_policy" {
#   statement {
#     sid    = "allows3"
#     effect = "Allow"
#     actions   = ["s3:*"]
#     resources = ["*"]
#   }
# }

# Prefect S3
data "aws_iam_policy_document" "prefect_s3_policy" {
  statement {
    sid    = "allows3limited"
    effect = "Allow"
    actions   = [
      "s3:ListBucket",
      "s3:ListBucketVersions",
      "s3:GetObject",
      "s3:GetObjectTagging",
      "s3:GetObjectVersion",
      "s3:PutObject"
    ]
    resources = var.prefect_s3_bucket_arns
  }
}

data "aws_iam_policy_document" "prefect_s3_full_policy" {
  statement {
    sid    = "allows3full"
    effect = "Allow"
    actions   = [
      "s3:ListBucket",
      "s3:ListBucketVersions",
      "s3:GetObject",
      "s3:GetObjectTagging",
      "s3:GetObjectVersion",
      "s3:PutObject",
      "s3:DeleteObject"
    ]
    resources = var.prefect_s3_bucket_arns_full_access
  }
}

# Prefect Parameter Store
data "aws_iam_policy_document" "prefect_parameter_policy" {
  statement {
    sid    = "allowparameters"
    effect = "Allow"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:${local.region}:${data.aws_caller_identity.current.account_id}:parameter/*"]
  }
}

# Prefect Secrets Manager
data "aws_iam_policy_document" "prefect_secrets_policy" {
  statement {
    sid    = "allowsecrets"
    effect = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["arn:aws:secretsmanager:${local.region}:${data.aws_caller_identity.current.account_id}:secret:*"]
  }
}

# combine all policy docs defined below for the service_role
data "aws_iam_policy_document" "prefect_ecs_service_role_policy_doc" {
  source_policy_documents = [
    data.aws_iam_policy_document.prefect_s3_policy.json,
    data.aws_iam_policy_document.prefect_parameter_policy.json,
    data.aws_iam_policy_document.prefect_secrets_policy.json,
    data.aws_iam_policy_document.prefect_ecs_policy.json,
    data.aws_iam_policy_document.prefect_ecr_policy.json,
    data.aws_iam_policy_document.prefect_ec2_policy.json,
    data.aws_iam_policy_document.prefect_cloudwatch_policy.json
  ]
}

# Prefect ECS
data "aws_iam_policy_document" "prefect_ecs_policy" {
  statement {
    sid    = "allowecs"
    effect = "Allow"
    actions   = [
                "ecs:*",
                "iam:PassRole"
            ]
    resources = ["*"]
  }
}

# Prefect ECR
data "aws_iam_policy_document" "prefect_ecr_policy" {
  statement {
    sid    = "allowecr"
    effect = "Allow"
    actions   = ["ecr:*"]
    resources = ["*"]
  }
}

# # Prefect Parameter Store
# data "aws_iam_policy_document" "prefect_parameter_policy" {
#   statement {
#     sid    = "allowparameters"
#     effect = "Allow"
#     actions   = ["ssm:GetParameter"]
#     resources = ["arn:aws:ssm:${local.region}:${data.aws_caller_identity.current.account_id}:parameter/*"]
#   }
# }

# Prefect EC2
data "aws_iam_policy_document" "prefect_ec2_policy" {
  statement {
    sid    = "allowec2"
    effect = "Allow"
    actions   = [
      "ec2:DescribeVpcs",
      "ec2:DescribeSubnets"
    ]
    resources = ["*"]
  }
}

# Prefect cloudwatch
data "aws_iam_policy_document" "prefect_cloudwatch_policy" {
  statement {
    sid    = "allowlogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:CreateLogGroup",
      "logs:PutLogEvents"
    ]
    resources = [
      "arn:aws:logs:*:${data.aws_caller_identity.current.account_id}:log-group:*:log-stream:*"
    ]
  }
}

# Prefect work pool job configuration
data "template_file" "ecs_work_pool_config" {
  for_each = var.clusters
  template = file(format("./base_job_template.tpl"))

  vars = {
    vpc_id = var.vpc_id
    ecs_cluster = aws_ecs_cluster.prefect_worker_cluster[each.key].name
    task_definition_arn = aws_ecs_task_definition.prefect_job_task_definition[each.key].arn
    subnets = join("", var.private_subnet_id)
    security_groups = aws_security_group.prefect_worker.id
  }
}
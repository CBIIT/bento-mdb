resource "aws_iam_role" "prefect_ecs_task_role" {
  name                 = local.task_role_name
  assume_role_policy   = data.aws_iam_policy_document.ecs_trust_policy.json
  permissions_boundary = local.permission_boundary_arn
}

resource "aws_iam_role_policy_attachment" "prefect_ecs_task_role_attachment" {
  role       = aws_iam_role.prefect_ecs_task_role.name
  policy_arn = aws_iam_policy.ecs_task_role_policy.arn
}

resource "aws_iam_policy" "ecs_task_role_policy" {
  name   = local.task_role_policy_name
  policy = data.aws_iam_policy_document.prefect_ecs_task_role_policy_doc.json
}

resource "aws_iam_role" "prefect_ecs_service_role" {
  name                 = local.service_role_name
  assume_role_policy   = data.aws_iam_policy_document.ecs_trust_policy.json
  permissions_boundary = local.permission_boundary_arn
}

resource "aws_iam_role_policy_attachment" "prefect_ecs_service_role_attachment" {
  role       = aws_iam_role.prefect_ecs_service_role.name
  policy_arn = aws_iam_policy.ecs_service_role_policy.arn
}

resource "aws_iam_policy" "ecs_service_role_policy" {
  name   = local.service_role_policy_name
  policy = data.aws_iam_policy_document.prefect_ecs_service_role_policy_doc.json
} 
locals {
  # Global
  iam_prefix = terraform.workspace == "prod" || terraform.workspace == "stage" ? "" : "power-user-"
  permission_boundary_arn = terraform.workspace == "prod" || terraform.workspace == "stage" ? "" : "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/PermissionBoundary_PowerUser"
  region = "us-east-1"

  # SG
  any_port     = 0
  any_protocol = "-1"
  all_ips      =  ["0.0.0.0/0"]

  # IAM
  task_role_name = "${local.iam_prefix}prefect-ecs-task-${var.project}-${var.tier}"
  task_role_policy_name = "${local.iam_prefix}prefect-ecs-task-policy-${var.project}-${var.tier}"
  service_role_name = "${local.iam_prefix}prefect-ecs-service-${var.project}-${var.tier}"
  service_role_policy_name = "${local.iam_prefix}prefect-ecs-service-policy-${var.project}-${var.tier}"

  # ECS
  #ecs_worker_cluster_name = "prefect-worker-${var.project}-${var.tier}"
  ecs_exec_log_group = "${var.project}-${var.tier}-prefect-ecs-execute-command-logs"

  # EFS
  efs_security_group_ports = ["2049"]

}

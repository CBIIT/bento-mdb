# ECS
resource "aws_kms_key" "ecs_exec" {
  description         = "The AWS Key Management Service key that encrypts the data between the local client and the container."
  enable_key_rotation = true

  tags = {
    "Name" = format("%s-%s-%s", var.project, var.tier, "ecs-exec-kms-key")
  }
}

resource "aws_cloudwatch_log_group" "ecs_execute_command_log_group" {
  name              = local.ecs_exec_log_group
  retention_in_days = 90
}

resource "aws_ecs_cluster" "prefect_worker_cluster" {
  for_each = var.clusters
  name = "${each.value.name}-${var.tier}"

  configuration {
    execute_command_configuration {
      kms_key_id = aws_kms_key.ecs_exec.key_id
      logging    = "OVERRIDE"

      log_configuration {
        cloud_watch_log_group_name     = aws_cloudwatch_log_group.ecs_execute_command_log_group.name
        cloud_watch_encryption_enabled = false
      }
    }
  }
}

resource "aws_ecs_cluster_capacity_providers" "prefect_worker_cluster_capacity_providers" {
  for_each = var.clusters
  cluster_name       = "${each.value.name}-${var.tier}"
  capacity_providers = ["FARGATE"]
}

resource "aws_ecs_service" "prefect-worker-service" {
  for_each = var.clusters
  name                   = "${each.value.name}-${var.tier}"
  cluster                = "${each.value.name}-${var.tier}"
  task_definition        = aws_ecs_task_definition.prefect_worker_task_definition[each.key].arn
  desired_count          = each.value.worker_desired_count
  launch_type            = "FARGATE"
  enable_execute_command = true

  // Public IP required for pulling secrets and images
  // https://aws.amazon.com/premiumsupport/knowledge-center/ecs-unable-to-pull-secrets/
  network_configuration {
    security_groups  = [aws_security_group.prefect_worker.id]
    // assign_public_ip = true
    subnets          = var.private_subnet_id
  }

}

# EFS
resource "aws_efs_file_system" "prefect_efs" {
  for_each = var.clusters
  creation_token = "efs-${each.value.name}-${var.tier}"
  performance_mode = "generalPurpose"
  throughput_mode = "bursting"
  encrypted = "true"
   
  tags = {
   "Name" = format("%s-%s", "${each.value.name}-${var.tier}", "efs")
  }

 }

resource "aws_efs_mount_target" "efs-mt" {
  for_each = var.clusters
  #count = length(var.private_subnet_id)
  file_system_id  = aws_efs_file_system.prefect_efs[each.key].id
  #subnet_id = var.private_subnet_id[count.index]
  subnet_id = var.private_subnet_id[0]
  security_groups = [aws_security_group.prefect_efs.id]
 }
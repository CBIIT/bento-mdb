resource "aws_ecs_task_definition" "prefect_worker_task_definition" {
  for_each = var.clusters
  family = "prefect-worker-${each.value.name}-${var.tier}"
  cpu    = each.value.worker_cpu
  memory = each.value.worker_memory

  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"

  // NOTE: if using ecs worker type update the following
  //
  //     "command": ["/bin/sh -c \"prefect worker start --pool ${var.worker_work_pool_name}\""],
  //     "image": "${var.job_image}",
  //
  //  to:
  //
  //     "command": ["/bin/sh -c \"yum -y install python-pip && pip install prefect-aws && prefect worker start --pool ${var.worker_work_pool_name}\""],
  //     "image": "${var.worker_image}",  

  container_definitions = <<DEFINITION
  [
    {
      "name": "prefect-worker-${each.value.name}-${var.tier}",
      "entryPoint": ["sh","-c"],
      "command": ["/bin/sh -c \"yum -y install python-pip && pip install prefect==3.2.8 prefect-aws==0.5.5 && prefect worker start --pool ${each.value.name}-prefect-${each.value.job_prefect_version}\""],
      "image": "${each.value.worker_image}",
      "cpu": ${each.value.worker_cpu},
      "memory": ${each.value.worker_memory},
      "environment": [
        {
          "name": "PREFECT_API_URL",
          "value": "https://api.prefect.cloud/api/accounts/${var.prefect_account_id}/workspaces/${var.prefect_workspace_id}"
        },
        {
          "name": "PREFECT_API_KEY",
          "value": "${var.prefect_api_key}"
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/${var.project}/${var.tier}/worker-${each.value.name}-${var.tier}/logs",
          "awslogs-region": "${local.region}",
          "awslogs-create-group": "true",
          "awslogs-stream-prefix": "${var.project}"
        }
      }
    }
  ]
  DEFINITION

  // Execution role allows ECS to create tasks and services
  execution_role_arn = aws_iam_role.prefect_ecs_service_role.arn
  // Task role allows tasks and services to access other AWS resources
  // Use worker_task_role_arn if provided, otherwise populate with default
  task_role_arn = aws_iam_role.prefect_ecs_service_role.arn
}


resource "aws_ecs_task_definition" "prefect_job_task_definition" {
  for_each = var.clusters
  family = "prefect-job-${each.value.name}-${var.tier}"
  cpu    = each.value.job_cpu
  memory = each.value.job_memory

  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"

  container_definitions = <<DEFINITION
  [
    {
      "name": "prefect-job-${each.value.name}-${var.tier}",
      "image": "${each.value.job_image}",
      "cpu": ${each.value.job_cpu},
      "memory": ${each.value.job_memory},
      "mountPoints": [
        {
          "containerPath": "/usr/local/data",
          "sourceVolume": "prefect-efs-storage",
          "readOnly": false
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/${var.project}/${var.tier}/job-${each.value.name}-${var.tier}/logs",
          "awslogs-region": "${local.region}",
          "awslogs-create-group": "true",
          "awslogs-stream-prefix": "${var.project}"
        }
      }
    }
  ]
  DEFINITION

  volume {
    name = "prefect-efs-storage"

    efs_volume_configuration {
      file_system_id          = aws_efs_file_system.prefect_efs[each.key].id
      //root_directory          = "/usr/local/data"
      transit_encryption      = "ENABLED"
    }
  }

  // Execution role allows ECS to create tasks and services
  execution_role_arn = aws_iam_role.prefect_ecs_service_role.arn
  // Task role allows tasks and services to access other AWS resources
  // Use worker_task_role_arn if provided, otherwise populate with default
  task_role_arn = aws_iam_role.prefect_ecs_task_role.arn
}
# ECS
resource "aws_security_group" "prefect_worker" {
  name        = "prefect-worker-sg-${var.project}-${var.tier}"
  description = "${var.tier} ECS Prefect worker"
  vpc_id      = var.vpc_id
}

resource "aws_security_group_rule" "all_egress_ecs" {
  security_group_id = aws_security_group.prefect_worker.id
  from_port         = local.any_port
  protocol          = local.any_protocol
  to_port           = local.any_port
  cidr_blocks       = local.all_ips
  type              = "egress"
}

# EFS
resource "aws_security_group" "prefect_efs" {
   name = "${var.project}-${var.tier}-efs-sg"
   description= "Allows inbound efs traffic"
   vpc_id = var.vpc_id

   tags = {
      "Name" = format("%s-%s-%s", var.project, "efs", "sg")
    }
}

resource "aws_security_group_rule" "all_egress_efs" {
  security_group_id = aws_security_group.prefect_efs.id
  from_port         = local.any_port
  protocol          = local.any_protocol
  to_port           = local.any_port
  cidr_blocks       = local.all_ips
  type              = "egress"
}

resource "aws_security_group_rule" "ingress_efs" {
  for_each          = toset(local.efs_security_group_ports)
  from_port         = each.key
  protocol          = "tcp"
  to_port           = each.key
  security_group_id = aws_security_group.prefect_efs.id
  cidr_blocks       = [data.aws_vpc.vpc.cidr_block]
  type              = "ingress"
}
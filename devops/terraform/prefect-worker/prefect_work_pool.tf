resource "prefect_work_pool" "ecs" {
  for_each = var.clusters
  name         = "${each.value.name}-prefect-${each.value.job_prefect_version}"
  type         = each.value.work_pool_type
  paused       = false
  workspace_id = var.prefect_workspace_id
  base_job_template = data.template_file.ecs_work_pool_config[each.key].rendered
}
variable "project" {
  description = "project for this worker deployment"
  type        = string
}

variable "tier" {
  description = "tier for this worker deployment"
  type        = string
}

variable "vpc_id" {
  description = "ID for the VPC to be used"
  type        = string
}

variable "private_subnet_id" {
  description = "ID for the subnet to be used"
  type        = list(string)
}

variable "prefect_account_id" {
  description = "Prefect cloud account ID"
  type        = string
}

variable "prefect_workspace_id" {
  description = "Prefect cloud workspace ID"
  type        = string
}

variable "prefect_api_key" {
  description = "Prefect API key"
  type        = string 
}

variable "clusters" {
  type = map(object({
    name                      = string
    worker_cpu                = number
    worker_memory             = number
    worker_image              = string
    worker_type               = string
    worker_desired_count      = number
    job_cpu                   = number
    job_memory                = number
    job_image                 = string
    job_prefect_version       = string
    work_pool_type            = string
  }))
}

variable "prefect_s3_bucket_arns" {
  description = "A list of bucket ARNs that will need to be accessed by the job"
  type        = list(string)
}

variable "prefect_s3_bucket_arns_full_access" {
  description = "A list of bucket ARNs that will need to be granted full access for the job"
  type        = list(string)
  default     = []
}
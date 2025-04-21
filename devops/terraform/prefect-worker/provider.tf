terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 4.0"
    }
    prefect = {
      source = "prefecthq/prefect"
    }
  }
}

provider "aws" {
  region = local.region

  default_tags {
   tags = {
     EnvironmentTier = var.tier
     Project         = var.project
     CreatedBy       = "CTOS DevOps"
     ResourceName    = "${var.project}-prefect"
     ManagedBy       = "CTOS DevOps"
     ApplicationName = var.project
   }
  }
}

provider "prefect" {
  account_id = var.prefect_account_id
  api_key    = var.prefect_api_key
}
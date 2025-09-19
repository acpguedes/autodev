terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

variable "region" {
  type        = string
  default     = "us-east-1"
  description = "Default AWS region for provisioning AutoDev resources"
}

output "placeholder" {
  description = "Reminder that no infrastructure resources are provisioned yet"
  value       = "AutoDev infrastructure bootstrap is pending implementation"
}

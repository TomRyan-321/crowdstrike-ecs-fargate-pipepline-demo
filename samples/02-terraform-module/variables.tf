variable "aws_region" {
  type        = string
  description = "AWS region to deploy into"
  default     = "us-west-2"
}

variable "name_prefix" {
  type        = string
  description = "Prefix for the task definition family and log group"
  default     = "ecs-fargate-demo"
}

variable "app_image" {
  type        = string
  description = "Application container image URI including tag or digest"
}

variable "falcon_image" {
  type        = string
  description = "Falcon Container sensor image URI in a registry the task execution role can pull from (e.g. a private ECR mirror)"
}

variable "falcon_cid" {
  type        = string
  description = "CrowdStrike Customer ID (CID) including checksum"
  sensitive   = true
}

variable "falcon_sensor_tags" {
  type        = string
  description = "Comma-separated Falcon sensor grouping tags, e.g. \"ecs-fargate-demo\" (empty for none)"
  default     = ""
}

variable "execution_role_arn" {
  type        = string
  description = "ARN of an existing ECS task execution role"
}

variable "log_retention_days" {
  type        = number
  description = "CloudWatch Logs retention for the application log group"
  default     = 7
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to all resources"
  default = {
    sample    = "02-terraform-module"
    ManagedBy = "terraform"
  }
}

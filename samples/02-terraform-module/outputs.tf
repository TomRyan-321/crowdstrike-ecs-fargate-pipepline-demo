output "task_definition_arn" {
  description = "ARN of the registered task definition revision"
  value       = module.falcon_ecs_task.task_definition_arn
}

output "log_group_name" {
  description = "CloudWatch log group for the application container"
  value       = module.falcon_ecs_task.log_group_name
}

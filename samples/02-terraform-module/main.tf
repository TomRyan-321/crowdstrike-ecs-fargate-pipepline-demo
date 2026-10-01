# The CrowdStrike module builds a Fargate task definition with the Falcon init container,
# shared volume, entrypoint wrapper, FALCONCTL_OPTS and SYS_PTRACE added for you.
module "falcon_ecs_task" {
  source = "github.com/CrowdStrike/terraform-aws-ecs-fargate?ref=v0.0.2"

  app_name  = "${var.name_prefix}-terraform-module"
  app_image = var.app_image

  # Set the image's ENTRYPOINT and CMD explicitly so the Falcon wrapper launches them
  # (matches app/Dockerfile).
  app_entrypoint = ["python"]
  app_command    = ["app.py"]

  app_port_mappings = [
    {
      containerPort = 8080
      protocol      = "tcp"
    }
  ]

  app_environment = [
    {
      name  = "DEMO_SAMPLE"
      value = "02-terraform-module"
    }
  ]

  # Left writable: with a read-only root filesystem the sensor also needs a per-container
  # /tmp/CrowdStrike-private volume, which the module (v0.0.2) does not create.
  app_readonly_root_filesystem = false

  falcon_image = var.falcon_image
  falcon_cid   = var.falcon_cid

  # Appended to FALCONCTL_OPTS after --cid, the same place the patching utility puts falconctl options
  falcon_additional_opts = var.falcon_sensor_tags != "" ? "--tags=${var.falcon_sensor_tags}" : ""

  task_cpu    = "512"
  task_memory = "1024"

  create_execution_role = false
  execution_role_arn    = var.execution_role_arn

  log_group_name     = "/ecs/${var.name_prefix}-terraform-module"
  log_retention_days = var.log_retention_days

  tags = var.tags
}

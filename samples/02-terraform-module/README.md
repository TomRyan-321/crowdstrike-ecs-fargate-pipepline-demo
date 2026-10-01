# 02: CrowdStrike Terraform module

[`CrowdStrike/terraform-aws-ecs-fargate`](https://github.com/CrowdStrike/terraform-aws-ecs-fargate) builds an `aws_ecs_task_definition` that already includes:

- The Falcon init container
- The shared sensor volume and mount
- The `dependsOn` ordering
- The Falcon entrypoint wrapper
- `FALCONCTL_OPTS` containing your CID
- `SYS_PTRACE`

You describe your application container, and the module adds the Falcon pieces.

Sensor grouping tags come from `falcon_sensor_tags`, which this sample sets as the `FALCONCTL_OPT_TAGS` environment variable on the app container.

The root filesystem stays writable here. With a read-only root filesystem, the sensor also needs a per-container `/tmp/CrowdStrike-private` volume, and the module doesn't create one yet.

The pipeline stores state in the S3 bucket created by the bootstrap stack, with native S3 locking. To run it locally:

```bash
cp terraform.tfvars.example terraform.tfvars   # fill in your values
terraform init \
  -backend-config="bucket=<TF_STATE_BUCKET>" \
  -backend-config="key=ecs-fargate-demo/02-terraform-module.tfstate" \
  -backend-config="region=us-west-2"
terraform apply
```

`falcon_image` must point to a registry that the task execution role can pull from at task start. The pipeline mirrors the sensor into ECR for that reason.

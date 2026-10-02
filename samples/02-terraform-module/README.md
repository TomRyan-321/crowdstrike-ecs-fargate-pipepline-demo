# 02: CrowdStrike Terraform module

[`CrowdStrike/terraform-aws-ecs-fargate`](https://github.com/CrowdStrike/terraform-aws-ecs-fargate) generates an `aws_ecs_task_definition` with the Falcon pieces already in place:

- the Falcon init container, `crowdstrike-falcon-init-container`, which copies the sensor into a shared volume and exits
- the shared sensor volume, mounted at `/tmp/CrowdStrike` in your container
- for a read-only root filesystem, a writable `crowdstrike-private-<app_name>` volume at `/tmp/CrowdStrike-private` (module v0.0.3 or later)
- `dependsOn: COMPLETE`, so your container starts after the init container finishes
- the Falcon entrypoint wrapper in front of your entrypoint
- `FALCONCTL_OPTS` with your CID, plus any `falcon_additional_opts`, such as `--tags`
- the `SYS_PTRACE` capability

You describe the application container as you normally would. [`main.tf`](main.tf) is the complete example.

## Run it locally

Complete the [one-time local setup](../README.md#one-time-local-setup) first. You'll need Terraform 1.10 or later.

### 1. Choose where state lives

[`versions.tf`](versions.tf) declares an S3 backend, which the pipeline configures at `init` time. For a local trial, override it with local state. `*_override.tf` files are git-ignored:

```bash
cd samples/02-terraform-module
cat > backend_override.tf <<'EOF'
terraform {
  backend "local" {}
}
EOF
terraform init
```

To share state with the pipeline instead, skip the override and point `init` at the bootstrap's state bucket:

```bash
terraform init \
  -backend-config="bucket=ecs-fargate-demo-tfstate-$ACCOUNT_ID-$AWS_REGION" \
  -backend-config="key=$NAME_PREFIX/02-terraform-module.tfstate" \
  -backend-config="region=$AWS_REGION"
```

### 2. Plan and apply

Pass the inputs as environment variables, so the CID isn't written to a `tfvars` file. ([`terraform.tfvars.example`](terraform.tfvars.example) lists the same inputs if you prefer a file.)

```bash
export TF_VAR_aws_region=$AWS_REGION
export TF_VAR_name_prefix=$NAME_PREFIX
export TF_VAR_app_image=$APP_IMAGE
export TF_VAR_falcon_image=$FALCON_IMAGE
export TF_VAR_falcon_cid=$FALCON_CID
export TF_VAR_falcon_sensor_tags=$FALCON_SENSOR_TAGS
export TF_VAR_execution_role_arn=$TASK_EXECUTION_ROLE_ARN

terraform plan -out=tfplan
terraform apply tfplan
terraform output task_definition_arn
```

The CID is sensitive in Terraform, but it's still stored in the state file and in the task definition's environment. Protect the state accordingly.

### 3. See what the module generated

```bash
aws ecs describe-task-definition --task-definition "$NAME_PREFIX-terraform-module" \
  --query 'taskDefinition.containerDefinitions[].{name: name, entryPoint: entryPoint, command: command, dependsOn: dependsOn, env: environment}' \
  | sed -E 's/--cid=[^ "]+/--cid=<redacted>/'
```

Then [run and verify the task](../README.md#running-and-verifying-a-protected-task) with the `${NAME_PREFIX}-terraform-module` family. To remove everything, run `terraform destroy`.

## Use it in CI

The pipeline's `sample-02-terraform-module` job runs `terraform init` (with the S3 backend), `plan` and `apply`, and passes the same inputs as `TF_VAR_*` variables. State lives in the bootstrap's S3 bucket and uses native S3 locking (`use_lockfile = true`), so you don't need a DynamoDB table.

## Adapting it

- **Entrypoint and command:** set `app_entrypoint` and `app_command` to your image's `ENTRYPOINT` and `CMD`; this sample uses `["python"]` and `["app.py"]`. The module wraps the entrypoint with the Falcon launcher. If you leave it unset, the module relies on the sensor discovering the image's default entrypoint, which is less reliable.
- **Sensor options:** `falcon_additional_opts` is appended to `FALCONCTL_OPTS` after `--cid`. This sample passes `--tags=<falcon_sensor_tags>`, which is CrowdStrike's documented way to set sensor grouping tags.
- **Read-only root filesystem:** this sample sets `app_readonly_root_filesystem = true`. The sensor then needs a writable `/tmp/CrowdStrike-private` directory, so the module (v0.0.3 or later) adds a `crowdstrike-private-<app_name>` volume and the init container makes it writable. Earlier module versions fail at start-up with `mkdir: cannot create directory '/tmp/CrowdStrike-private': Read-only file system`.
- **Log retention:** the module creates the log group with `log_retention_days`, which this sample sets to 7 by default.
- **Execution role:** the sample passes in an existing role (`create_execution_role = false`). The module can also create one for you.
- **Sizing:** the init container reserves 256 CPU units and 512 MiB while it runs (`falcon_init_cpu`, `falcon_init_memory`), so size the task for that on top of your app.
- **ARM64:** set `runtime_platform = { cpu_architecture = "ARM64" }`. The module switches the loader path automatically, and the mirrored sensor image is multi-architecture.
- **Services:** the module outputs the task definition ARN. Pass it to your `aws_ecs_service` along with the `platform_version` and `enable_execute_command` outputs.

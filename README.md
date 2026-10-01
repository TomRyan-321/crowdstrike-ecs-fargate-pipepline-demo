# CrowdStrike Falcon on Amazon ECS Fargate: pipeline samples

This repository shows how to protect Amazon ECS Fargate workloads with the **CrowdStrike Falcon Container sensor** from a GitHub Actions pipeline. Every method starts from the same small Python app and ends with a registered ECS task definition that runs the app with Falcon runtime protection.

Pick the sample that matches how you already deploy to ECS:

| # | Sample | How Falcon is added | Best fit when you... |
|---|--------|---------------------|----------------------|
| 01 | [falconutil patch-image](samples/01-falconutil-patched-image) | The sensor is embedded into a new copy of your image at build time with [`crowdstrike/falconutil-action`](https://github.com/CrowdStrike/falconutil-action) | Ship images through a pipeline, deploy with any tool, and want minimal changes to task definitions |
| 02 | [Terraform module](samples/02-terraform-module) | [`CrowdStrike/terraform-aws-ecs-fargate`](https://github.com/CrowdStrike/terraform-aws-ecs-fargate) builds the task definition with the Falcon init container | Manage ECS with Terraform |
| 03 | [Task definition patch](samples/03-task-definition-patch) | The Falcon patching utility rewrites a task definition JSON file | Register task definitions from JSON (AWS CLI, ECS deploy actions, CodePipeline) |
| 04 | [CloudFormation patch](samples/04-cloudformation-patch) | The Falcon patching utility rewrites a CloudFormation template | Manage ECS with CloudFormation |

### How the sensor gets into the task

Samples 02 to 04 use the **init container** pattern. The application image is not modified. At task start, a non-essential Falcon init container copies the sensor into a shared volume. The application container then waits for it (`dependsOn: COMPLETE`), mounts the volume, launches through the Falcon entrypoint wrapper, and gets the `SYS_PTRACE` capability.

![Init container pattern: the Falcon init container copies the sensor into a shared volume, then the application container starts through the Falcon entrypoint](docs/images/init-container-pattern.svg)

Sample 01 uses the **patched image** pattern. Those pieces are built into the image at build time, so the task definition only needs `SYS_PTRACE`. The Falcon Container sensor runs in user space inside the application container and protects every process the app starts.

![Patched image pattern: falconutil combines the application image and the sensor into a patched image that runs on ECS Fargate](docs/images/patched-image-pattern.svg)

In both patterns, the sensor runs inside each application container and sends telemetry to the CrowdStrike cloud. Fargate gives no access to the host kernel, and the sensor doesn't need it.

## What the pipeline does

[`.github/workflows/cs-ecs-fargate-demo.yaml`](.github/workflows/cs-ecs-fargate-demo.yaml) runs these jobs:

```text
iac-scan ──► build ──┬──► 01 falconutil patch-image ──► register task definition
                     ├──► 02 Terraform module         ──► terraform apply
                     ├──► 03 task definition patch    ──► register task definition
                     └──► 04 CloudFormation patch     ──► cloudformation deploy
```

1. **iac-scan** scans this repository's Terraform, CloudFormation and task definitions with the [Falcon Cloud Security IaC scanner](https://github.com/CrowdStrike/fcs-action). It uploads the SARIF results to GitHub code scanning and to the Falcon console.
2. **build** does the following:
   - Builds `app/` and scans the image with Falcon Cloud Security image assessment. Pass or fail comes from your **Image Assessment policy** in the Falcon console. The results go to the Falcon console, to GitHub code scanning as SARIF, and to a workflow artifact.
   - Pushes the image to Amazon ECR.
   - Mirrors the Falcon Container sensor image from the CrowdStrike registry into a private ECR repository with [`falcon-container-sensor-pull.sh`](https://github.com/CrowdStrike/falcon-scripts/tree/main/bash/containers/falcon-container-sensor-pull). The sensor is multi-architecture, and Fargate pulls it at task start.
3. **Samples 01-04** run in parallel. Each one produces a task definition protected by Falcon.

The samples register task definitions only. They do not create clusters or services, so they cost almost nothing to run. To start a protected task, use any of the resulting task definitions with your own cluster and network:

```bash
aws ecs run-task --cluster <cluster> --launch-type FARGATE \
  --task-definition ecs-fargate-demo-terraform-module \
  --network-configuration 'awsvpcConfiguration={subnets=[subnet-xxxx],securityGroups=[sg-xxxx],assignPublicIp=ENABLED}'
```

The task needs outbound access (a public IP or NAT) to reach ECR and the Falcon cloud. Once the task is running, the sensor registers with your Falcon tenant and shows up in host management.

## Following a run in GitHub Actions

Each run's **Summary** page is written to be presented as-is, from top to bottom:

1. **Run overview:** what triggered the run, which AWS environment it used, the Falcon cloud, the sensor version and the grouping tags.
2. **Scan results:** IaC findings and image vulnerabilities by severity, with the top issues in expandable lists. Both scans also appear under **Security → Code scanning**, where you can filter by the `crowdstrike-fcs-iac` and `crowdstrike-fcs-image` categories.
3. **Sensor mirror:** which Falcon Container sensor version the init container samples use.
4. **One card per sample,** all built from the task definition that ECS actually registered, so the four methods can be compared directly:
   - The containers and their start order, including the Falcon init container where one is used.
   - How each application container launches, for example `Falcon wrapper → python app.py`.
   - The Falcon settings: `SYS_PTRACE`, the sensor volume mounts and the sensor configuration (`FALCONCTL_OPTS`, `FALCONCTL_OPT_TAGS`).
   - A link to the task definition in the AWS console.
   - For sample 01, a before and after view of the image's entrypoint and environment.

Your CID is redacted and the AWS account ID is hidden, so the page is safe to share on screen. In the job logs, noisy output such as the full patch diffs and the sensor download is folded into collapsed groups. The run graph (`iac-scan → build → 01 | 02 | 03 | 04`) shows the four methods running side by side.

### Demo findings and scan enforcement

The demo app is **intentionally a little out of date** so the image assessment has something to show. It uses the `python:3.12.7-alpine3.20` base image and older Flask, Werkzeug, Jinja2, waitress and click releases, with a handful of known CVEs; see [`app/requirements.txt`](app/requirements.txt). GitHub Dependabot will flag the same packages. Bump them to current releases before you reuse the app for anything else.

By default, failed scans **warn and the pipeline keeps going**. This means a vulnerable image still reaches the four samples, and the findings stay visible in the summary. To block on failed scans instead (the IaC `fail_on` thresholds or the Image Assessment policy), set:

```bash
gh variable set ENFORCE_SCAN_RESULTS --body true
```

## Security model

AWS access uses **GitHub OIDC**, so no long-lived AWS keys are stored in GitHub.

- The IAM role trusts exactly two OIDC subjects, and both belong to this one repository:
  - `repo:<owner>/<repo>:environment:aws-main`
  - `repo:<owner>/<repo>:environment:aws-approval`

  Tokens for pull requests, other branches, tags and other repositories are rejected.
- **`aws-main`** has a deployment branch policy that allows only `main`. Pushes to `main` and the weekly scheduled run deploy automatically.
- **`aws-approval`** has a required reviewer. Any run from another branch (via **Run workflow** / `workflow_dispatch`) pauses until the reviewer approves. Expect two approval prompts per run: one for `build`, then one that releases all four sample jobs together.
- The workflow has **no `pull_request` trigger**. The repository also requires approval before workflows run for outside contributors.
- The role's permissions are scoped to the sample's resources:
  - Push/pull on three ECR repositories
  - Registering ECS task definitions
  - `iam:PassRole` on the single task execution role
  - Log groups under `/ecs/ecs-fargate-demo-*`
  - The Terraform state bucket
  - The single sample CloudFormation stack, `ecs-fargate-demo-cloudformation-patch`. The role can't touch the bootstrap stack that defines it.

## Set it up in your own account

### Prerequisites

- An AWS account, and admin credentials for the one-time bootstrap (AWS CLI v2).
- The GitHub CLI (`gh`), authenticated with admin access to your copy of this repository.
- A CrowdStrike API client with these scopes:

  | Scope | Permission | Used by |
  |-------|-----------|---------|
  | Sensor Download | Read | Sensor image pull, falconutil |
  | Falcon Images Download | Read | Sensor image pull, falconutil |
  | Cloud Security Tools Download | Read | FCS CLI download |
  | Infrastructure as Code | Read, Write | IaC scan |
  | Falcon Container CLI | Read, Write | Image scan |
  | Falcon Container Image | Read, Write | Image scan |

### 1. Bootstrap AWS and GitHub (once)

```bash
# Optional overrides: AWS_REGION (default us-west-2), FALCON_CLOUD (default us-1),
# NAME_PREFIX (default ecs-fargate-demo), REVIEWER (default: your gh login),
# FALCON_SENSOR_TAGS (comma-separated sensor grouping tags, default none)
FALCON_SENSOR_TAGS=cs-myteam-ecs-demo bootstrap/setup.sh <owner>/<repo>
```

[`bootstrap/setup.sh`](bootstrap/setup.sh) does three things:

1. Deploys [`bootstrap/bootstrap.yaml`](bootstrap/bootstrap.yaml), which creates:
   - The GitHub OIDC provider (it reuses one that already exists in the account)
   - The deploy role
   - ECR repositories for `app`, `app-falcon-patched` and `falcon-container`
   - A shared task execution role
   - A versioned, encrypted S3 bucket for Terraform state, using native S3 locking
2. Creates the `aws-main` and `aws-approval` GitHub environments with the protections described above.
3. Stores the stack outputs as repository variables: `AWS_REGION`, `AWS_ROLE_ARN`, `TASK_EXECUTION_ROLE_ARN`, `TF_STATE_BUCKET`, `NAME_PREFIX`, `FALCON_CLOUD` and (when set) `FALCON_SENSOR_TAGS`.

### 2. Add your CrowdStrike credentials

```bash
gh secret set FALCON_CLIENT_ID
gh secret set FALCON_CLIENT_SECRET
gh secret set FALCON_CID   # your CID including the checksum, e.g. 1234567890ABCDEF1234567890ABCDEF-12
```

### 3. Run it

Push to `main`, or start **Actions > CrowdStrike Falcon ECS Fargate samples > Run workflow**. The workflow uses the latest sensor by default. To pin a sensor version, set the `falcon_sensor_version` input (for example `7.38.0-7703`).

## Adapting a sample to your application

- **Entrypoint and command:** the Falcon wrapper must launch your application's real entrypoint. The patching utility reads it from the image when the task definition does not set one. The Terraform module needs it explicitly (`app_entrypoint` / `app_command`). This app uses `ENTRYPOINT ["python"]` and `CMD ["app.py"]`.
- **Sizing:** the Terraform module gives the init container 256 CPU units and 512 MiB by default, so the init container samples use a 512 CPU / 1024 MiB task.
- **Architecture:** all samples target `X86_64`. For Graviton, set the task's `cpuArchitecture` to `ARM64`, and also set `falcon_image_platform: aarch64` for falconutil. The mirrored sensor image already includes both architectures.
- **Read-only root filesystem:** samples 03 and 04 set `readonlyRootFilesystem: true`. In that case the patching utility also adds a writable `/tmp/CrowdStrike-private` volume to each container. The Terraform module (v0.0.2) doesn't add that volume, so sample 02 keeps the root filesystem writable.
- **Other sensor options:** set them the same way as tags. Use `-falconctl-opts "--tags=... --billing=metered"` with the utilities, or add more `FALCONCTL_OPT_*` environment variables (for example `FALCONCTL_OPT_BILLING`) in Terraform.

## Sensor grouping tags

Sensor grouping tags let you target these containers with Falcon host groups and policies, and filter them in the console. The pipeline reads a comma-separated list from the `FALCON_SENSOR_TAGS` repository variable and applies it to every sample:

| Sample | How the tags are set | Resulting setting |
|--------|----------------------|-------------------|
| 01 falconutil patch-image | `falconctl_opts: --tags=<tags>` on `falconutil-action` | Built into the patched image |
| 02 Terraform module | `falcon_sensor_tags` variable, added as an app container environment variable | `FALCONCTL_OPT_TAGS=<tags>` |
| 03 / 04 patching utility | `-falconctl-opts "--tags=<tags>"` | Added to the patched task definition |

`FALCONCTL_OPT_TAGS` is the environment variable form of `falconctl --tags`. Each variable in the `FALCONCTL_OPT_*` family maps to one `falconctl` option. To change the tags:

```bash
gh variable set FALCON_SENSOR_TAGS --body "cs-myteam-ecs-demo,production"
```

## Repository layout

```text
app/                  Demo Flask application and Dockerfile
docs/images/          Architecture diagrams
bootstrap/            One-time AWS (CloudFormation) and GitHub setup
samples/
  01-falconutil-patched-image/   Task definition for the falconutil-patched image
  02-terraform-module/           Terraform using CrowdStrike/terraform-aws-ecs-fargate
  03-task-definition-patch/      Task definition JSON patched by the Falcon utility
  04-cloudformation-patch/       CloudFormation template patched by the Falcon utility
.github/workflows/    The pipeline and the demo teardown
.github/scripts/      Job summary renderer used by the pipeline
```

## Clean up

**To reset between demos,** run **Actions → CrowdStrike Falcon ECS Fargate samples - teardown → Run workflow**. It:

- deletes the CloudFormation sample stack
- runs `terraform destroy` for sample 02
- deregisters the task definitions for samples 01 and 03 and deletes their log groups

The bootstrap stack, ECR repositories and Terraform state stay in place, so the next run starts straight away. Like the main workflow, the teardown runs automatically from `main` and needs approval from any other branch.

**To remove everything,** run the teardown first, then use admin credentials:

```bash
aws ecr delete-repository --force --repository-name ecs-fargate-demo/app   # repeat for app-falcon-patched, falcon-container
aws cloudformation delete-stack --stack-name ecs-fargate-demo-bootstrap   # the state bucket is retained
```

## Documentation and references

**CrowdStrike documentation**

- [Deploy the Falcon Container sensor on Amazon ECS Fargate](https://docs.crowdstrike.com/r/en-US/iopiipqy/a5c297cc). Requires a Falcon login.

**CrowdStrike tools used by the pipeline**

| Tool | Used for |
|------|----------|
| [CrowdStrike/fcs-action](https://github.com/CrowdStrike/fcs-action) | IaC scanning and container image assessment with the Falcon Cloud Security CLI |
| [CrowdStrike/falconutil-action](https://github.com/CrowdStrike/falconutil-action) | `falconutil patch-image` (sample 01) |
| [CrowdStrike/terraform-aws-ecs-fargate](https://github.com/CrowdStrike/terraform-aws-ecs-fargate) | Terraform module for Falcon-protected task definitions (sample 02) |
| [falcon-container-sensor-pull.sh](https://github.com/CrowdStrike/falcon-scripts/tree/main/bash/containers/falcon-container-sensor-pull) | Mirroring the Falcon Container sensor image into Amazon ECR (from [CrowdStrike/falcon-scripts](https://github.com/CrowdStrike/falcon-scripts)) |

**Third-party actions used by the pipeline**

| Action | Used for |
|--------|----------|
| [actions/checkout](https://github.com/actions/checkout) | Checking out the repository |
| [aws-actions/configure-aws-credentials](https://github.com/aws-actions/configure-aws-credentials) | Assuming the AWS role via GitHub OIDC |
| [aws-actions/amazon-ecr-login](https://github.com/aws-actions/amazon-ecr-login) | Docker login to Amazon ECR |
| [github/codeql-action](https://github.com/github/codeql-action) (`upload-sarif`) | Publishing IaC scan results to GitHub code scanning |
| [actions/upload-artifact](https://github.com/actions/upload-artifact) | Keeping the image scan report as a workflow artifact |
| [hashicorp/setup-terraform](https://github.com/hashicorp/setup-terraform) | Installing Terraform (sample 02) |

This is a community sample, not an officially supported CrowdStrike product.

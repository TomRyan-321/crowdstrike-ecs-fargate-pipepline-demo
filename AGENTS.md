# AGENTS.md

Guidance for AI coding agents (Claude Code, Codex, Copilot, Cursor and others) that are asked to **stand up this repository in a user's own AWS account and GitHub repository**, or to change it. Read [README.md](README.md) for the full design. This file is the operating procedure. If the human wants to patch tasks **without the pipeline**, follow [samples/README.md](samples/README.md) and the per-sample local guides instead.

## What this repository deploys

- **One-time bootstrap** ([`bootstrap/bootstrap.yaml`](bootstrap/bootstrap.yaml), applied by [`bootstrap/setup.sh`](bootstrap/setup.sh)):
  - a GitHub OIDC provider and a deploy role scoped to one repository
  - ECR repositories and a task execution role
  - an S3 bucket for Terraform state
  - an ECS cluster, a small public VPC with an outbound-only security group, and an EventBridge Scheduler group and role

  Nothing in the bootstrap costs money while idle (there are no NAT gateways or load balancers).
- **The pipeline** ([`.github/workflows/cs-ecs-fargate-demo.yaml`](.github/workflows/cs-ecs-fargate-demo.yaml)) scans with CrowdStrike Falcon Cloud Security and registers four Falcon-protected ECS Fargate task definitions. It does not run services.
- **The optional detection container stage** runs one **Fargate Spot** task (0.5 vCPU / 1 GiB, with a public IP) for one hour. That costs a few cents per run. Keep demo tasks on `FARGATE_SPOT`.

## Ask the human first

Do not guess these. Confirm each one before you change anything:

1. **Target AWS account and region.** Run `aws sts get-caller-identity` and show the account ID to the human. The bootstrap needs admin-level credentials. The default region is `us-west-2` (`AWS_REGION`).
2. **Target GitHub repository** (`owner/repo`), usually the human's fork or copy. The authenticated `gh` user needs admin rights on it.
3. **Falcon cloud** for their tenant: `us-1`, `us-2`, `eu-1`, `us-gov-1` or `us-gov-2` (`FALCON_CLOUD`).
4. **Sensor grouping tags** (`FALCON_SENSOR_TAGS`, comma-separated, lowercase recommended), or none.
5. **Approver** for runs from non-main branches (`REVIEWER`). It defaults to the `gh` user.

## Never handle Falcon credentials yourself

The CrowdStrike API client secret and CID are the human's to enter. Don't ask for them in chat, don't read them from files or environment variables, and don't write them anywhere. Give the human these commands to run. Each one prompts for the value:

```bash
gh secret set FALCON_CLIENT_ID     --repo <owner>/<repo>
gh secret set FALCON_CLIENT_SECRET --repo <owner>/<repo>
gh secret set FALCON_CID           --repo <owner>/<repo>   # CID including checksum, e.g. ...ABCD-12
```

The API client needs these scopes:

| Scope | Permission |
|---|---|
| Sensor Download | Read |
| Falcon Images Download | Read |
| Cloud Security Tools Download | Read |
| Infrastructure as Code | Read + Write |
| Falcon Container CLI | Read + Write |
| Falcon Container Image | Read + Write |

Confirm the secrets exist with `gh secret list` (it shows names only).

## Standing it up

```bash
# 0. Tools: aws (v2), gh (authenticated, admin on the repo), jq
aws sts get-caller-identity
gh auth status

# 1. Bootstrap AWS and GitHub (idempotent; safe to re-run)
AWS_REGION=us-west-2 FALCON_CLOUD=us-1 FALCON_SENSOR_TAGS=ecs-fargate-demo \
  bootstrap/setup.sh <owner>/<repo>

# 2. The human sets the three Falcon secrets (see above)

# 3. Forks only: Actions starts disabled on forks; enable it (or ask the human to use the Actions tab)
gh api -X PUT repos/<owner>/<repo>/actions/permissions -F enabled=true

# 4. Run the pipeline from the default branch (no approval needed on main)
gh workflow run cs-ecs-fargate-demo.yaml --repo <owner>/<repo> --ref main
# Optional: only one sample and/or the detection container
gh workflow run cs-ecs-fargate-demo.yaml --repo <owner>/<repo> --ref main \
  -f sample=02-terraform-module -f detection_container=true
```

`setup.sh` creates the `aws-main` and `aws-approval` environments, requires approval before workflows run for outside contributors, and stores every stack output the workflows need as repository variables. Check the result with `gh variable list --repo <owner>/<repo>`.

## Verifying

- **Workflow:** run `gh run watch <run-id>` or `gh run view <run-id>`. Every job should succeed, and the sample jobs should be skipped when you selected `sample=none`.
- **Task definitions:** `aws ecs list-task-definitions --family-prefix ecs-fargate-demo-`.
- **Detection container:**
  - Find the task with `aws ecs list-tasks --cluster ecs-fargate-demo --family ecs-fargate-demo-detection-container`.
  - Its stop schedule appears in `aws scheduler list-schedules --group-name ecs-fargate-demo`.
  - Its logs are in `/ecs/ecs-fargate-demo-detection-container`; each scenario prints a line starting with `===`.
- **Falcon:** the human confirms detections and hosts in the Falcon console. Hosts appear under **Host management**, filtered by **Pod ID** (the ECS task ID). You can't see the console yourself.
- **Run summary:** cards render on each run's Summary page, which is only visible to signed-in GitHub users.

## Tearing it down

- To remove what the pipeline deployed, run `gh workflow run ecs-fargate-demo-teardown.yaml --repo <owner>/<repo> --ref main`. It stops detection tasks and their schedules, deletes the CloudFormation sample stack, destroys the Terraform sample, and deregisters task definitions.
- To remove everything, follow the README's "Clean up" section. The bootstrap stack retains the Terraform state bucket on deletion.

Confirm with the human before you delete stacks, repositories or buckets.

## Known gotchas

- **`workflow_dispatch` needs the workflow file on the default branch.** That's why the file keeps its original name, `cs-ecs-fargate-demo.yaml`. Don't rename it. A new workflow file can only be dispatched after it's merged.
- **GitHub disables scheduled workflows after 60 days without activity.** If dispatch fails with "disabled workflow", run `gh workflow enable cs-ecs-fargate-demo.yaml`.
- **An AWS account can have only one GitHub OIDC provider.** `setup.sh` detects an existing provider and reuses it (`CreateOIDCProvider=false`).
- **Gated jobs use `environment: { name: ..., deployment: false }`.** With deployment records, GitHub can't approve several parallel jobs waiting on the same environment ("There was a problem approving one of the gates"). Keep `deployment: false`.
- **One approval per branch run.** The `build` job deliberately has no AWS access. Only the sample jobs and the detection container job use the gated environment, and they wait on it together. Don't add AWS steps to `build`.
- **The sample app pins slightly outdated versions on purpose,** so the image assessment has findings to show. Don't "fix" them unless the human asks.
- **Scans warn rather than block** unless the `ENFORCE_SCAN_RESULTS` repository variable is `true`.
- **Read-only root filesystems need a writable `/tmp/CrowdStrike-private` volume.** The patching utility (samples 03, 04) and the Terraform module from v0.0.3 (sample 02) add it. Don't pin sample 02 below v0.0.3.
- **Log groups expire after 7 days** (`LOG_RETENTION_DAYS`). Samples 01 and 03 and the detection container use `awslogs-create-group`, which can't set retention, so their jobs create the group with a retention policy before ECS writes to it. Keep that step if you add new task definitions.
- **The detection container image is cached in ECR** under `<sensor version>-<hash of the sensor tags>`. Changing the tags or the sensor version triggers a fresh patch.

## Changing the repository

- **Validate before committing:**

  ```bash
  actionlint
  cfn-lint bootstrap/bootstrap.yaml samples/04-cloudformation-patch/cloudformation.yaml
  shellcheck bootstrap/setup.sh
  python3 -m py_compile .github/scripts/summary.py
  (cd samples/02-terraform-module && terraform fmt -check && terraform init -backend=false && terraform validate)
  ```

- **Keep the security model intact:**
  - Don't add a `pull_request` trigger.
  - Don't widen the OIDC trust beyond the two environment subjects.
  - Keep IAM permissions scoped to `${NamePrefix}` resources.
  - If you change the deploy role, check it with `aws accessanalyzer validate-policy`.
- **Use CrowdStrike tools:** use CrowdStrike tooling and the documented CrowdStrike methods (`fcs-action`, `falconutil`, the patching utility, `--tags` through falconctl options) for scanning and sensor configuration. Don't add GitHub Dependabot, CodeQL or other scanners.
- **No account identifiers:** don't hardcode AWS account IDs, CIDs or tenant identifiers. Use repository variables, stack outputs and `envsubst` placeholders. Summary output redacts the CID and shortens ECR hostnames.
- **Keep the README as public reference documentation:** no presenter notes or demo scripts.

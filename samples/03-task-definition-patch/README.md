# 03: Patch a task definition JSON file

The Falcon Container sensor image includes a **patching utility**. When you run the image with `-ecs-spec-file`, the utility reads an ECS task definition (the `aws ecs register-task-definition --cli-input-json` format) and writes a patched copy to stdout. For every container in the task, it:

- adds the `crowdstrike-falcon-init-container` init container, plus the shared `crowdstrike-falcon-volume` volume
- adds `dependsOn: COMPLETE` on the init container
- mounts `/tmp/CrowdStrike` (and, for a read-only root filesystem, a private `/tmp/CrowdStrike-private` volume)
- wraps the entrypoint with `/tmp/CrowdStrike/rootfs/entrypoint-ecs.sh`, keeping your entrypoint and command
- adds `FALCONCTL_OPTS` with your CID and any `-falconctl-opts`
- adds the `SYS_PTRACE` capability

[`taskdefinition.json`](taskdefinition.json) is the input used here. It's an ordinary task definition with `${...}` placeholders, which `envsubst` fills in.

## Run it locally

Complete the [one-time local setup](../README.md#one-time-local-setup) first. Run these commands from the repository root.

### 1. Render the input

```bash
mkdir -p build
envsubst '${NAME_PREFIX} ${APP_IMAGE} ${AWS_REGION} ${TASK_EXECUTION_ROLE_ARN}' \
  < samples/03-task-definition-patch/taskdefinition.json > build/taskdefinition.json
```

### 2. Create a registry pull token

The utility reads each container image's `ENTRYPOINT` and `CMD` from the registry when the task definition doesn't set them, so it needs read access to your images. The token is a base64-encoded Docker `config.json` `auths` block. ECR tokens are valid for 12 hours.

```bash
ECR_AUTH=$(printf 'AWS:%s' "$(aws ecr get-login-password)" | base64 | tr -d '\n')
PULL_TOKEN=$(printf '{"auths":{"%s":{"auth":"%s"}}}' "$REGISTRY" "$ECR_AUTH" | base64 | tr -d '\n')
```

If you're already signed in with a file-based Docker config (see [setup step 3](../README.md#3-a-docker-config-that-stores-credentials-in-the-file)), `PULL_TOKEN=$(base64 < "$DOCKER_CONFIG/config.json" | tr -d '\n')` works too.

### 3. Patch it

```bash
falconctl_opts=()
[ -n "$FALCON_SENSOR_TAGS" ] && falconctl_opts=(-falconctl-opts "--tags=$FALCON_SENSOR_TAGS")

docker run --rm --platform linux/amd64 \
  -v "$PWD/build:/spec" \
  "$FALCON_IMAGE" \
  -cid "$FALCON_CID" \
  -image "$FALCON_IMAGE" \
  -pulltoken "$PULL_TOKEN" \
  "${falconctl_opts[@]}" \
  -ecs-spec-file /spec/taskdefinition.json > build/taskdefinition.patched.json

diff <(jq -S . build/taskdefinition.json) <(jq -S . build/taskdefinition.patched.json) | sed -E 's/--cid=[^ "]+/--cid=<redacted>/'
```

- `-image` is the sensor image that the **task** pulls at start. Point it at your ECR mirror, not at the CrowdStrike registry.
- `-falconctl-opts` takes any `falconctl` options in a single string, for example `"--tags=a,b --billing=metered"`.
- To pass the task definition on stdin instead of mounting a file, use `-ecs-spec "$(cat build/taskdefinition.json)"`.

### 4. Register it

```bash
aws ecs register-task-definition --cli-input-json file://build/taskdefinition.patched.json \
  --query taskDefinition.taskDefinitionArn --output text
```

The utility drops the task definition's resource `tags`. If you rely on them, add them back on registration: `--tags key=sample,value=03-task-definition-patch`.

Then [run and verify the task](../README.md#running-and-verifying-a-protected-task) with the `${NAME_PREFIX}-task-definition-patch` family.

## Patch an existing task definition

To protect a workload that's already registered, export its task definition, strip the read-only fields that `register-task-definition` rejects, patch it, and register the result as a new revision:

```bash
FAMILY="<your task definition family>"
aws ecs describe-task-definition --task-definition "$FAMILY" --query taskDefinition \
  | jq 'del(.taskDefinitionArn, .revision, .status, .requiresAttributes, .compatibilities,
            .registeredAt, .registeredBy, .deregisteredAt)' > build/existing.json

docker run --rm --platform linux/amd64 -v "$PWD/build:/spec" "$FALCON_IMAGE" \
  -cid "$FALCON_CID" -image "$FALCON_IMAGE" -pulltoken "$PULL_TOKEN" "${falconctl_opts[@]}" \
  -ecs-spec-file /spec/existing.json > build/existing.patched.json

aws ecs register-task-definition --cli-input-json file://build/existing.patched.json
```

Then update your service to the new revision with `aws ecs update-service --task-definition`. If the definition already references the sensor because it was patched before, start again from the unpatched source rather than patching twice.

## Private registries with repository credentials

If a container uses `repositoryCredentials` (a Secrets Manager secret for a private registry), the utility can fetch that secret itself through the AWS SDK. Mount your AWS credentials into the container at `/.aws` instead of passing `-pulltoken`:

```bash
docker run --rm --platform linux/amd64 -v "$HOME/.aws:/.aws:ro" -v "$PWD/build:/spec" "$FALCON_IMAGE" \
  -cid "$FALCON_CID" -image "$FALCON_IMAGE" -ecs-spec-file /spec/taskdefinition.json > build/taskdefinition.patched.json
```

The container user must be able to read the mounted files. CrowdStrike's docs suggest `chmod a+r ~/.aws/credentials`, so consider using a dedicated, short-lived profile for this. The SDK resolves credentials in its usual order: environment variables, shared config files, then a task or instance role.

## Use it in CI

The pipeline's `sample-03-task-definition-patch` job runs these same steps: render, pull token, patch, register. It prints the full diff in a collapsed log group and warns if the sensor tags are missing from the patched output.

## Adapting it

- **Commit the unpatched source.** Patch it at deploy time, so the sensor version and CID never live in source control.
- **Exclude a container:** add `"dockerLabels": {"sensor.falcon-system.crowdstrike.com/injection": "disabled"}` to it before patching.
- **Read-only root filesystem:** this sample sets `readonlyRootFilesystem: true`. The utility handles it by adding the private volume.
- **Multi-container tasks:** every container is patched, except those with the injection label disabled. Each container gets its own private volume when it needs one.

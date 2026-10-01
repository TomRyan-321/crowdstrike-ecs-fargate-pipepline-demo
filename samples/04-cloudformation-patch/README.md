# 04: Patch a CloudFormation template

The same patching utility as [sample 03](../03-task-definition-patch) also understands CloudFormation templates, in JSON or YAML. It patches every `AWS::ECS::TaskDefinition` resource, adding the init container, volumes, `dependsOn`, wrapped entrypoint, `FALCONCTL_OPTS` and `SYS_PTRACE`. It leaves the rest of the template alone. You then deploy the patched template as usual.

[`cloudformation.yaml`](cloudformation.yaml) is the input used here: a task definition with its log group, with the image passed in as the `AppImagePath` parameter.

## Run it locally

Complete the [one-time local setup](../README.md#one-time-local-setup) first. Run these commands from the repository root.

### 1. Create a registry pull token

```bash
mkdir -p build
cp samples/04-cloudformation-patch/cloudformation.yaml build/cloudformation.yaml
ECR_AUTH=$(printf 'AWS:%s' "$(aws ecr get-login-password)" | base64 | tr -d '\n')
PULL_TOKEN=$(printf '{"auths":{"%s":{"auth":"%s"}}}' "$REGISTRY" "$ECR_AUTH" | base64 | tr -d '\n')
```

### 2. Patch the template

When an image comes from a template **parameter**, the utility can't resolve it by itself. Pass the value with `-cloudformationParams` (in the AWS CLI `ParameterKey=...,ParameterValue=...` format), so it can inspect the image's entrypoint and command:

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
  -cloudformationParams "ParameterKey=AppImagePath,ParameterValue=$APP_IMAGE" \
  -ecs-spec-file /spec/cloudformation.yaml > build/cloudformation.patched.yaml

# The patched task definition resource (the part Falcon changes)
yq '.Resources.TaskDefinition.Properties' build/cloudformation.patched.yaml | sed -E 's/--cid=[^ "]+/--cid=<redacted>/'
```

The utility re-serialises the whole template. Keys come out sorted alphabetically, short-form intrinsics such as `!Ref` become their long form (`Ref:`), and folded strings are collapsed onto one line. That makes a plain `diff` against the original noisy, so inspect the `AWS::ECS::TaskDefinition` resources instead. CloudFormation treats both forms the same.

### 3. Deploy it

```bash
aws cloudformation deploy \
  --stack-name "$NAME_PREFIX-cloudformation-patch" \
  --template-file build/cloudformation.patched.yaml \
  --no-fail-on-empty-changeset \
  --parameter-overrides \
    NamePrefix="$NAME_PREFIX" \
    AppImagePath="$APP_IMAGE" \
    ExecutionRoleArn="$TASK_EXECUTION_ROLE_ARN"

aws cloudformation describe-stacks --stack-name "$NAME_PREFIX-cloudformation-patch" \
  --query "Stacks[0].Outputs[?OutputKey=='TaskDefinitionArn'].OutputValue" --output text
```

Then [run and verify the task](../README.md#running-and-verifying-a-protected-task) with the `${NAME_PREFIX}-cloudformation-patch` family. To remove it, run `aws cloudformation delete-stack --stack-name "$NAME_PREFIX-cloudformation-patch"`.

## Use it in CI

The pipeline's `sample-04-cloudformation-patch` job patches the template on every run and deploys it with `aws cloudformation deploy`. Commit only the **unpatched** template. The sensor version and CID are added at deploy time, so they never live in source control.

## Adapting it

- **Several task definitions in one template:** all of them are patched in one pass. Every image the utility needs to inspect must be resolvable, either as a literal image URI or as a parameter whose value you pass with `-cloudformationParams`.
- **CDK and SAM:** run the utility on the synthesized template (`cdk synth` output or the packaged SAM template), then deploy that file.
- **Images set as literals** (rather than through parameters) don't need `-cloudformationParams`.
- **Exclude a container:** add the `sensor.falcon-system.crowdstrike.com/injection: disabled` Docker label to it before patching.

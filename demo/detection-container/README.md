# Detection container on Fargate

This runs CrowdStrike's [detection container](https://github.com/CrowdStrike/detection-container) as a Falcon-protected ECS Fargate task, so you can see real detections in the Falcon console. The detection container bundles harmless scripts that mimic attacker behaviour, such as credential dumping, reverse shells, ransomware-style file encryption and container drift.

The image is protected with the [patched image method (01)](../../samples/01-falconutil-patched-image). [`taskdefinition.json`](taskdefinition.json) overrides the container's `command` so the task:
- first runs every bundled scenario, about 15 seconds apart, each capped at two minutes
- then hands over to the container's own auto mode, which triggers a random scenario every few minutes

Only `command` is overridden, not `entryPoint`, so the Falcon entrypoint built into the image still launches first.

## Run it locally

Complete the [one-time local setup](../../samples/README.md#one-time-local-setup) first. You can skip step 6 (building the sample app). Run these commands from the repository root.

### 1. Patch the detection container

```bash
SOURCE_IMAGE=quay.io/crowdstrike/detection-container:latest
export DETECTION_IMAGE=$REGISTRY/$NAME_PREFIX/detection-container:local
docker pull --platform linux/amd64 "$SOURCE_IMAGE"

LOCAL_SENSOR=$(bash falcon-container-sensor-pull.sh --region "$FALCON_CLOUD" --type falcon-container \
  --version "$SENSOR_VERSION" --platform x86_64 | grep '^registry.*/falcon-container' | tail -n 1)

falconctl_opts=()
[ -n "$FALCON_SENSOR_TAGS" ] && falconctl_opts=(--falconctl-opts "--tags=$FALCON_SENSOR_TAGS")

docker run --rm --platform linux/amd64 --user 0:0 \
  -v "$DOCKER_CONFIG/config.json:/root/.docker/config.json" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  "$LOCAL_SENSOR" \
  falconutil patch-image \
    --source-image-uri "$SOURCE_IMAGE" \
    --target-image-uri "$DETECTION_IMAGE" \
    --falcon-image-uri "$LOCAL_SENSOR" \
    --cid "$FALCON_CID" \
    --cloud-service ECS_FARGATE \
    --image-pull-policy IfNotPresent \
    "${falconctl_opts[@]}"

docker push "$DETECTION_IMAGE"
```

If you didn't run the bootstrap, create the repository first with `aws ecr create-repository --repository-name "$NAME_PREFIX/detection-container"`.

### 2. Register and run the task

```bash
envsubst '${NAME_PREFIX} ${DETECTION_IMAGE} ${AWS_REGION} ${TASK_EXECUTION_ROLE_ARN}' \
  < demo/detection-container/taskdefinition.json > /tmp/detection-container.json
TASK_DEF=$(aws ecs register-task-definition --cli-input-json file:///tmp/detection-container.json \
  --query taskDefinition.taskDefinitionArn --output text)

out() { aws cloudformation describe-stacks --stack-name ecs-fargate-demo-bootstrap \
          --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
export CLUSTER=$(out DemoClusterName) SUBNETS=$(out DemoSubnetIds) SECURITY_GROUP=$(out DemoSecurityGroupId)

TASK_ARN=$(aws ecs run-task --cluster "$CLUSTER" \
  --capacity-provider-strategy capacityProvider=FARGATE_SPOT,weight=1 \
  --task-definition "$TASK_DEF" \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SECURITY_GROUP],assignPublicIp=ENABLED}" \
  --query 'tasks[0].taskArn' --output text)
aws ecs wait tasks-running --cluster "$CLUSTER" --tasks "$TASK_ARN"
echo "Task ID (Falcon Pod ID): ${TASK_ARN##*/}"
```

The task runs on Fargate Spot, in a public subnet whose security group has no inbound rules. Its public IP is only used for outbound traffic to ECR and the CrowdStrike cloud. If you use your own network, any subnet with outbound internet access (a public IP or NAT) works.

### 3. Watch it and find the detections

```bash
aws logs tail "/ecs/$NAME_PREFIX-detection-container" --follow   # each scenario starts with "=== <name>"
```

In the Falcon console, the detections carry your sensor grouping tag. Find the host under **Host setup and management → Manage endpoints → Host management**, filtering on **Pod ID** = the task ID.

### 4. Stop it

Stop it by hand:

```bash
aws ecs stop-task --cluster "$CLUSTER" --task "$TASK_ARN" >/dev/null
```

Or schedule the stop the way the pipeline does. This one-time EventBridge Scheduler schedule stops the task after an hour and then deletes itself. It uses the scheduler role and schedule group from the bootstrap:

```bash
STOP_AT=$(date -u -v+60M +%Y-%m-%dT%H:%M:%S 2>/dev/null || date -u -d '+60 minutes' +%Y-%m-%dT%H:%M:%S)
aws scheduler create-schedule --name "stop-${TASK_ARN##*/}" --group-name "$NAME_PREFIX" \
  --schedule-expression "at($STOP_AT)" --schedule-expression-timezone UTC \
  --flexible-time-window Mode=OFF --action-after-completion DELETE \
  --target "$(jq -n --arg role "$(out StopTaskSchedulerRoleArn)" --arg cluster "$CLUSTER" --arg task "$TASK_ARN" \
    '{Arn: "arn:aws:scheduler:::aws-sdk:ecs:stopTask", RoleArn: $role,
      Input: ({Cluster: $cluster, Task: $task, Reason: "Scheduled stop"} | tojson)}')"
```

## Use it in CI

Start **Actions → CrowdStrike Falcon ECS Fargate samples → Run workflow** and tick **detection_container**. Choose `none` under **sample** to run only this stage. The job:
- reuses a cached patched image for the current sensor version and tags, or builds one
- runs the task on Fargate Spot
- schedules the one-hour stop
- links the running task from the run summary

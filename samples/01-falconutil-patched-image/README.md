# 01: Patch the image with falconutil

`falconutil patch-image --cloud-service ECS_FARGATE` builds a **new image** that contains your application, the Falcon Container sensor, your CID and any sensor options. The image's entrypoint becomes the Falcon entrypoint (`/opt/CrowdStrike/rootfs/bin/falcon-entrypoint`), which starts the sensor and then runs your original entrypoint and command.

Because the sensor ships inside the image, the task definition doesn't need an init container, a shared volume or a wrapped entrypoint. It needs one Falcon-specific setting:

```json
"linuxParameters": { "capabilities": { "add": ["SYS_PTRACE"] } }
```

[`taskdefinition.json`](taskdefinition.json) is a complete example. It uses `${...}` placeholders, which `envsubst` fills in.

`falconutil` ships inside the Falcon Container sensor image (version 7.19 or later is required for ECS Fargate). You can run it in a container on any OS with Docker, or copy the binary out and run it directly on Linux.

## Run it locally

Complete the [one-time local setup](../README.md#one-time-local-setup) first. These steps assume the variables from it are still exported in your shell.

### 1. Pull the sensor image for the target architecture

`patch-image` works on a single architecture, so pull the x86_64 sensor locally rather than using the multi-architecture ECR mirror:

```bash
LOCAL_SENSOR=$(bash falcon-container-sensor-pull.sh --region "$FALCON_CLOUD" --type falcon-container \
  --version "$SENSOR_VERSION" --platform x86_64 | grep '^registry.*/falcon-container' | tail -n 1)
echo "$LOCAL_SENSOR"
```

### 2. Patch the application image

```bash
export PATCHED_IMAGE=$REGISTRY/$NAME_PREFIX/app-falcon-patched:local

falconctl_opts=()
[ -n "$FALCON_SENSOR_TAGS" ] && falconctl_opts=(--falconctl-opts "--tags=$FALCON_SENSOR_TAGS")

docker run --rm --platform linux/amd64 --user 0:0 \
  -v "$DOCKER_CONFIG/config.json:/root/.docker/config.json" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  "$LOCAL_SENSOR" \
  falconutil patch-image \
    --source-image-uri "$APP_IMAGE" \
    --target-image-uri "$PATCHED_IMAGE" \
    --falcon-image-uri "$LOCAL_SENSOR" \
    --cid "$FALCON_CID" \
    --cloud-service ECS_FARGATE \
    --image-pull-policy IfNotPresent \
    "${falconctl_opts[@]}"

docker push "$PATCHED_IMAGE"
```

`--image-pull-policy IfNotPresent` makes `falconutil` use the images already on your machine: the app image you built and the sensor you just pulled. With `Always`, it pulls both images from their registries, using the credentials in the mounted `config.json`.

On Linux you can run the binary directly instead of in a container:

```bash
id=$(docker create "$LOCAL_SENSOR") && docker cp "$id:/usr/bin/falconutil" ./falconutil && docker rm -v "$id"
./falconutil patch-image --source-image-uri "$APP_IMAGE" --target-image-uri "$PATCHED_IMAGE" \
  --falcon-image-uri "$LOCAL_SENSOR" --cid "$FALCON_CID" --cloud-service ECS_FARGATE \
  --image-pull-policy IfNotPresent "${falconctl_opts[@]}"
```

### 3. See what changed

```bash
for image in "$APP_IMAGE" "$PATCHED_IMAGE"; do
  docker image inspect "$image" --format '{{.Config.Entrypoint}} {{.Config.Cmd}}'
done
docker image inspect "$PATCHED_IMAGE" --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -E '^(FALCON|CS_)' | sed -E 's/--cid=[^ ]+/--cid=<redacted>/'
```

### 4. Register the task definition

```bash
APP_IMAGE=$PATCHED_IMAGE envsubst '${NAME_PREFIX} ${APP_IMAGE} ${AWS_REGION} ${TASK_EXECUTION_ROLE_ARN}' \
  < samples/01-falconutil-patched-image/taskdefinition.json > /tmp/taskdefinition-01.json
aws ecs register-task-definition --cli-input-json file:///tmp/taskdefinition-01.json \
  --query taskDefinition.taskDefinitionArn --output text
```

Then [run and verify the task](../README.md#running-and-verifying-a-protected-task) with the `${NAME_PREFIX}-patched-image` family.

## Use it in CI

The pipeline's `sample-01-patched-image` job runs the same steps with [`crowdstrike/falconutil-action`](https://github.com/CrowdStrike/falconutil-action). The action downloads the sensor and runs `falconutil` for you:

```yaml
- uses: crowdstrike/falconutil-action@v1.1.0
  with:
    falcon_client_id: ${{ secrets.FALCON_CLIENT_ID }}
    falcon_region: us-1
    cid: ${{ secrets.FALCON_CID }}
    source_image_uri: <account>.dkr.ecr.<region>.amazonaws.com/app:<tag>
    target_image_uri: <account>.dkr.ecr.<region>.amazonaws.com/app-falcon-patched:<tag>
    cloud_service: ECS_FARGATE
    falconctl_opts: --tags=ecs-fargate-demo   # sensor grouping tags
    image_pull_policy: IfNotPresent
  env:
    FALCON_CLIENT_SECRET: ${{ secrets.FALCON_CLIENT_SECRET }}
```

## Adapting it

- **Entrypoint overrides:** if your task definition sets `entryPoint`, it replaces the Falcon entrypoint in the image. Combine them: `["/opt/CrowdStrike/rootfs/bin/falcon-entrypoint", "<your entrypoint>"]`. Overriding only `command` is fine.
- **Application grouping:** set the `CS_APP_NAME` environment variable in the container definition to group related containers by application name in the Falcon console. `CS_CLOUD_SERVICE` overrides the `--cloud-service` value at run time.
- **ARM64:** pull the sensor with `--platform aarch64`, build the app for `linux/arm64`, and set `cpuArchitecture: ARM64`. With the action, set `falcon_image_platform: aarch64`.
- **Sensor updates:** re-run `patch-image` with the new sensor version and roll out the new image tag. The task definition doesn't change, apart from the image.

# 03: Patch a task definition JSON file

The Falcon Container sensor image includes a patching utility. When you run the image with `-ecs-spec-file`, it reads a task definition (the `register-task-definition --cli-input-json` format) and writes a patched copy to stdout. The patched copy adds the Falcon init container, shared volume, `dependsOn`, entrypoint wrapper and `SYS_PTRACE` to every container.

```bash
docker run --rm --platform linux/amd64 -v "$PWD:/spec" "$FALCON_IMAGE" \
  -cid "$FALCON_CID" \
  -image "$FALCON_IMAGE" \
  -pulltoken "$PULL_TOKEN" \
  -falconctl-opts "--tags=cs-myteam-ecs-demo" \
  -ecs-spec-file /spec/taskdefinition.json > taskdefinition.patched.json

aws ecs register-task-definition --cli-input-json file://taskdefinition.patched.json
```

- `-image` is the sensor image that the task should pull at start. Use your private ECR mirror.
- `-falconctl-opts` passes `falconctl` options, such as sensor grouping tags, into the patched task definition as environment variables.
- `-pulltoken` is a base64-encoded Docker `config.json` auth for the registry. The utility uses it to read each application image's entrypoint and command when the task definition doesn't set them. The workflow shows how to build one for ECR.

`${...}` placeholders in the JSON are filled in by `envsubst` in the workflow.

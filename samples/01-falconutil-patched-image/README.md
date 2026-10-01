# 01: Patch the image with falconutil

[`crowdstrike/falconutil-action`](https://github.com/CrowdStrike/falconutil-action) runs `falconutil patch-image --cloud-service ECS_FARGATE`. That command produces a new image with the Falcon Container sensor and your CID embedded. The pipeline pushes the result to `ecs-fargate-demo/app-falcon-patched` and registers [`taskdefinition.json`](taskdefinition.json).

Because the sensor ships inside the image, this task definition has no init container or shared volume, and it does not wrap the entrypoint. It needs only one Falcon-specific setting:

```json
"linuxParameters": { "capabilities": { "add": ["SYS_PTRACE"] } }
```

```yaml
- uses: crowdstrike/falconutil-action@v1.1.0
  with:
    falcon_client_id: ${{ secrets.FALCON_CLIENT_ID }}
    falcon_region: us-1
    cid: ${{ secrets.FALCON_CID }}
    source_image_uri: <account>.dkr.ecr.<region>.amazonaws.com/app:<tag>
    target_image_uri: <account>.dkr.ecr.<region>.amazonaws.com/app-falcon-patched:<tag>
    cloud_service: ECS_FARGATE
    falconctl_opts: --tags=cs-myteam-ecs-demo   # sensor grouping tags
    image_pull_policy: IfNotPresent
  env:
    FALCON_CLIENT_SECRET: ${{ secrets.FALCON_CLIENT_SECRET }}
```

`${...}` placeholders in the JSON are filled in by `envsubst` in the workflow.

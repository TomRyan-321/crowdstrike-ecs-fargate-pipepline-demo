# 04: Patch a CloudFormation template

This is the same patching utility as sample 03, run against a CloudFormation template. It patches each `AWS::ECS::TaskDefinition` resource, and the pipeline then deploys the result with `aws cloudformation deploy`.

When the container image comes from a template parameter, pass the value with `-cloudformationParams`. The utility needs it to inspect the image:

```bash
docker run --rm --platform linux/amd64 -v "$PWD:/spec" "$FALCON_IMAGE" \
  -cid "$FALCON_CID" \
  -image "$FALCON_IMAGE" \
  -pulltoken "$PULL_TOKEN" \
  -falconctl-opts "--tags=cs-myteam-ecs-demo" \
  -cloudformationParams "ParameterKey=AppImagePath,ParameterValue=$APP_IMAGE" \
  -ecs-spec-file /spec/cloudformation.yaml > cloudformation.patched.yaml

aws cloudformation deploy --stack-name ecs-fargate-demo-cloudformation-patch \
  --template-file cloudformation.patched.yaml \
  --parameter-overrides AppImagePath="$APP_IMAGE" ExecutionRoleArn="$EXECUTION_ROLE_ARN"
```

Commit the unpatched template and patch it in the pipeline. That way the sensor version and CID never live in source control.

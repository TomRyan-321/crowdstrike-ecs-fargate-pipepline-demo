# crowdstrike-ecs-fargate-pipepline-demo

## About
This repository is used to demo building a dockerized application intended to be run on AWS ECS Fargate and leveraging CrowdStrike Falcon Container sensor to protect the application at runtime.

The Actions workflow demo [file](.github/workflows/cs-ecs-fargate-demo.yaml) does the following: 
 - Checks out a copy of this repository
 - Scans the repository with the Falcon Cloud Security Infrastructure as Code Scanner and uploads the resulting SARIF file
 - Builds and tags the Dockerfile
 - Scans the resulting image with CrowdStrike container image scanner service to check for Vulnerabilities/Malware/Secrets
 - Logs into AWS & ECR
 - Pushes the container image which was built to ECR
 - Pulls a copy of the Falcon Container image to perform the patching steps
 - Sample 1 - Patch an ECS Task definition JSON schema file [taskdefinition.json](taskdefinition.json) then uploads to patch definition to the ECS service using the `aws ecs register-task-definition` command syntax
 - Sample 2 - Patch an AWS CloudFormation template [cloudformation.yaml](cloudformation.yaml) then uploads the modified templates to the AWS CloudFormation service using the `aws cloudformation create-change-set` command syntax

Both methods injects the additional resources CrowdStrike requires which includes the following with each Task/ContainerDefinition within the templates:
 - Adds additional volumes for CrowdStrike resources
 - CrowdStrike init container (configures volumes and copies required files)
 - Sets DependsOn statements to ensure init container finishes before starting application containers
 - Adds the mount points to the users containers to be protected
 - Modifies the Entrypoint/CMD values to load CrowdStrike before the containers entrypoint (the patching utility queries the image using manifest at time of patching if not already specified within the template)
 - Enables the SYS_PTRACE Linux Capability in each protected container

 For more information refer to the official Documentation available within the Falcon platform for your respective Falcon cloud:
 [US-1](https://falcon.crowdstrike.com/documentation/146/falcon-container-sensor-for-linux#installing-falcon-container-sensor-for-linux-in-an-ecs-fargate-cluster)
 [US-2](https://falcon.us-2.crowdstrike.com/documentation/146/falcon-container-sensor-for-linux#installing-falcon-container-sensor-for-linux-in-an-ecs-fargate-cluster)
 [EU-1](https://falcon.eu-1.crowdstrike.com/documentation/146/falcon-container-sensor-for-linux#installing-falcon-container-sensor-for-linux-in-an-ecs-fargate-cluster)

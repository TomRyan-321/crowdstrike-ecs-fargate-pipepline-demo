# crowdstrike-ecs-fargate-pipepline-demo

## About
This repository is used to demo building a dockerized application intended to be run on AWS ECS Fargate and leveraging CrowdStrike Falcon Container sensor to protect the application at runtime. The Actions workflow builds the image, scans the image with CrowdStrike container image scanner service and then patches the users ECS Task Definition to include Falcon Container within the task definition and upload the patched task definition to AWS ECS.
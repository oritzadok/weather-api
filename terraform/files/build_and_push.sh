#!/bin/bash

set -euo pipefail

aws_region=$1
ecr_repo=$2

image=$ecr_repo

pushd ../src/
echo "Building Docker image"
docker build -t $image .
popd

echo "Logging into ECR repo"
aws ecr get-login-password --region $aws_region | docker login --username AWS --password-stdin $ecr_repo

echo "Pushing to ECR repository"
docker push $image

echo "Logging out of ECR repo"
docker logout $ecr_repo

echo "Deleting from local"
docker rmi $image
#!/bin/bash

set -euo pipefail

cd terraform

terraform init
terraform apply --auto-approve

echo "The web app will be publicly accessible soon on $(terraform output -raw app_url)/weather/"
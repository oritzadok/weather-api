#!/bin/bash

set -euo pipefail

cd terraform

terraform init
terraform destroy --auto-approve
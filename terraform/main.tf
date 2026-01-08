variable "aws_region" {
  type    = string
  default = "us-east-1"
}


variable "bucket_name" {
  type    = string
  default = "oritzadok-weatherapi-responses"
}


variable "openweather_api_key" {
  type        = string
  sensitive   = true # Mark as sensitive in UI/logs
}


terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.92"
    }

    github = {
      source  = "integrations/github"
      version = "~> 6.0"
    }
  }

  required_version = ">= 1.2"
}

provider "aws" {
  region = var.aws_region
}


resource "aws_s3_bucket" "bucket" {
  bucket        = var.bucket_name
  force_destroy = true
}


resource "aws_dynamodb_table" "table" {
  name         = "weatherapi-events"
  hash_key     = "city"
  billing_mode = "PAY_PER_REQUEST"
  range_key    = "timestamp"

  attribute {
    name = "city"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "N"
  }
}


resource "aws_ecr_repository" "repo" {
  name = "weatherapi"

  image_scanning_configuration {
    scan_on_push = true
  }

  force_delete = true
}


resource "null_resource" "build_first_image_tag" {
  provisioner "local-exec" {
    command = "./files/build_and_push.sh ${var.aws_region} ${aws_ecr_repository.repo.repository_url}"
  }
}


resource "aws_iam_role" "apprunner_ecr_access" {
  name = "AppRunnerECRAccessRole"
  path = "/service-role/"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "build.apprunner.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      },
    ]
  })
}


resource "aws_iam_role_policy_attachment" "apprunner_ecr_access" {
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess"
  role       = aws_iam_role.apprunner_ecr_access.name
}


resource "aws_iam_role" "apprunner_instance_role" {
  name = "AppRunnerInstanceRole"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "tasks.apprunner.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      },
    ]
  })
}


resource "aws_iam_policy" "apprunner_instance_role_policy" {
  name = "AppRunnerPolicyForInstanceRole"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "secretsmanager:GetSecretValue",
          "s3:PutObject",
          "dynamodb:PutItem"
        ]
        Effect   = "Allow"
        Resource = "*"
      },
    ]
  })
}


resource "aws_iam_role_policy_attachment" "apprunner_instance_role" {
  policy_arn = aws_iam_policy.apprunner_instance_role_policy.arn
  role       = aws_iam_role.apprunner_instance_role.name
}


resource "aws_secretsmanager_secret" "openweather_api_key" {
  name = "OpenWeather_API_Key"
}


resource "aws_secretsmanager_secret_version" "openweather_api_key" {
  secret_id     = aws_secretsmanager_secret.openweather_api_key.id
  secret_string = var.openweather_api_key
}


resource "aws_apprunner_service" "app" {
  service_name = "weather-api"

  source_configuration {
    authentication_configuration {
      access_role_arn = aws_iam_role.apprunner_ecr_access.arn
    }
    image_repository {
      image_configuration {
        port = "8000" # FastAPI default port
        runtime_environment_secrets = {
          OPENWEATHER_API_KEY = aws_secretsmanager_secret.openweather_api_key.arn
        }
        runtime_environment_variables = {
          DYNAMODB_TABLE_NAME = aws_dynamodb_table.table.name
          S3_BUCKET_NAME      = aws_s3_bucket.bucket.id
        }
      }
      image_identifier      = "${aws_ecr_repository.repo.repository_url}:latest"
      image_repository_type = "ECR"
    }

    auto_deployments_enabled = false
  }

  instance_configuration {
    instance_role_arn = aws_iam_role.apprunner_instance_role.arn
  }

  depends_on = [
    null_resource.build_first_image_tag,
    aws_iam_role_policy_attachment.apprunner_ecr_access,
    aws_iam_role_policy_attachment.apprunner_instance_role
  ]
}


output "aws_region" {
  value = var.aws_region
}


output "ecr_repository_uri" {
  value = aws_ecr_repository.repo.repository_url
}


output "app_url" {
  value = aws_apprunner_service.app.service_url
}
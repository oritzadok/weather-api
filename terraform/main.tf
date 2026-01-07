variable "aws_region" {
  type    = string
  default = "us-east-1"
}


variable "bucket_name" {
  type    = string
  default = "oritzadok-weatherapi-responses"
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


#resource "aws_dynamodb_table" "table" {
#  name           = "weatherapi-events"
#  hash_key       = "LockID"
#  read_capacity  = 20
#  write_capacity = 20
#
#  attribute {
#    name = "LockID"
#    type = "S"
#  }
#}
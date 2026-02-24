terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}
provider "aws" {
  region = "us-east-1"
}

resource "aws_instance" "monitor" {
  ami           = "ami-0c94855ba95c71c99"
  instance_type = "t3.micro"
  key_name      = "devops-key"

  tags = {
    Name = "MonitorInstance"
  }
}

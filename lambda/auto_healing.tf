# IAM Role for Lambda
resource "aws_iam_role" "lambda_auto_heal" {
  name = "lambda_auto_heal_role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

# IAM Policy for Lambda
resource "aws_iam_role_policy" "lambda_auto_heal_policy" {
  name = "lambda_auto_heal_policy"
  role = aws_iam_role.lambda_auto_heal.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ec2:DescribeInstances",
          "ec2:RebootInstances"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = ["sns:Publish"]
        Resource = aws_sns_topic.alerts.arn
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      }
    ]
  })
}

# Lambda Function
resource "aws_lambda_function" "auto_heal" {
  filename         = "lambda/auto_remediation.zip"
  function_name    = "auto_heal_ec2"
  role            = aws_iam_role.lambda_auto_heal.arn
  handler         = "auto_remediation.lambda_handler"
  source_code_hash = filebase64sha256("lambda/auto_remediation.zip")
  runtime         = "python3.11"
  timeout         = 60
  description      = "Auto-heal EC2 instances when CloudWatch alarms trigger"

  environment {
    variables = {
      SNS_TOPIC_ARN = aws_sns_topic.alerts.arn
    }
  }

  tags = {
    Name = "AutoHealEC2"
  }
}

# SNS Topic for Auto-Healing Trigger
resource "aws_sns_topic" "auto_heal_trigger" {
  name = "auto_heal_trigger"
}

# SNS Subscription: Trigger Lambda
resource "aws_sns_topic_subscription" "lambda_subscription" {
  topic_arn = aws_sns_topic.auto_heal_trigger.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.auto_heal.arn
}

# Lambda Permission for SNS
resource "aws_lambda_permission" "allow_sns" {
  statement_id  = "AllowExecutionFromSNS"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.auto_heal.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.auto_heal_trigger.arn
}

# CloudWatch Alarm: CPU Critical (triggers auto-healing)
resource "aws_cloudwatch_metric_alarm" "cpu_critical" {
  alarm_name          = "CriticalCPU-AutoHeal"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 300
  statistic           = "Average"
  threshold           = 90
  alarm_description   = "Triggers auto-healing when CPU > 90%"

  dimensions = {
    InstanceId = aws_instance.monitor.id
  }

  alarm_actions = [
    aws_sns_topic.auto_heal_trigger.arn,
    aws_sns_topic.alerts.arn
  ]

  tags = {
    Name = "AutoHeal-CPU"
  }
}

# CloudWatch Alarm: Memory Critical (triggers auto-healing)
resource "aws_cloudwatch_metric_alarm" "memory_critical" {
  alarm_name          = "CriticalMemory-AutoHeal"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "MemoryUsedPercent"
  namespace           = "CWAgent"
  period              = 300
  statistic           = "Average"
  threshold           = 90
  alarm_description   = "Triggers auto-healing when Memory > 90%"

  dimensions = {
    InstanceId = aws_instance.monitor.id
  }

  alarm_actions = [
    aws_sns_topic.auto_heal_trigger.arn,
    aws_sns_topic.alerts.arn
  ]

  tags = {
    Name = "AutoHeal-Memory"
  }
}

resource "aws_sns_topic" "alerts" {
  name = "monitoring_alerts"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "cpu_high" {
  alarm_name          = "HighCPUUtilization"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 300
  statistic           = "Average"
  threshold           = 80

  dimensions = {
    InstanceId = aws_instance.monitor.id
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "memory_high" {
  alarm_name          = "high-memory"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "MemoryUsedPercent"  # Changed to match your renamed metric
  namespace           = "CWAgent"
  period              = 300
  statistic           = "Average"
  threshold           = 80

  dimensions = {
    InstanceId = aws_instance.monitor.id
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "disk_high" {
  alarm_name          = "high-disk-usage"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "DiskUsedPercent"  # Changed to match your renamed metric
  namespace           = "CWAgent"
  period              = 300
  statistic           = "Average"
  threshold           = 80

  dimensions = {
    InstanceId = aws_instance.monitor.id
    path       = "/"
    device     = "xvda1"  # Fixed typo: was "xvdal"
    fstype     = "xfs"
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}

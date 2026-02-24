resource "aws_cloudwatch_dashboard" "monitoring_dashboard" {
  dashboard_name = "EC2-Monitoring-Dashboard"

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric"
        x    = 0
        y    = 0
        width = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/EC2", "CPUUtilization", { stat = "Average", label = "CPU Average" }],
            ["...", { stat = "Maximum", label = "CPU Max" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = "us-east-1"
          title   = "CPU Utilization"
          period  = 300
          yAxis = {
            left = {
              min = 0
              max = 100
            }
          }
        }
      },
      {
        type = "metric"
        x    = 12
        y    = 0
        width = 12
        height = 6
        properties = {
          metrics = [
            ["CWAgent", "MemoryUsedPercent", { stat = "Average" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = "us-east-1"
          title   = "Memory Utilization"
          period  = 300
          yAxis = {
            left = {
              min = 0
              max = 100
            }
          }
        }
      },
      {
        type = "metric"
        x    = 0
        y    = 6
        width = 12
        height = 6
        properties = {
          metrics = [
            ["CWAgent", "DiskUsedPercent", { stat = "Average" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = "us-east-1"
          title   = "Disk Utilization"
          period  = 300
          yAxis = {
            left = {
              min = 0
              max = 100
            }
          }
        }
      },
      {
        type = "metric"
        x    = 12
        y    = 6
        width = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/EC2", "NetworkIn", { stat = "Sum", label = "Network In" }],
            [".", "NetworkOut", { stat = "Sum", label = "Network Out" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = "us-east-1"
          title   = "Network Traffic"
          period  = 300
        }
      },
      {
        type = "metric"
        x    = 0
        y    = 12
        width = 24
        height = 6
        properties = {
          metrics = [
            ["CWAgent", "CPUUsageActive", { stat = "Average", label = "CPU Active" }],
            [".", "CPUUsageIdle", { stat = "Average", label = "CPU Idle" }]
          ]
          view    = "timeSeries"
          stacked = true
          region  = "us-east-1"
          title   = "CPU Usage Breakdown"
          period  = 300
          yAxis = {
            left = {
              min = 0
              max = 100
            }
          }
        }
      }
    ]
  })
}

output "dashboard_url" {
  value       = "https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards:name=${aws_cloudwatch_dashboard.monitoring_dashboard.dashboard_name}"
  description = "URL to view the CloudWatch Dashboard"
}

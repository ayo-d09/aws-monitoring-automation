# AWS Monitoring & Auto-Healing System

A production-ready AWS monitoring solution with automated incident response using CloudWatch, Lambda, and Terraform.

## Overview

This project demonstrates a complete cloud monitoring and auto-healing infrastructure that automatically detects and resolves EC2 instance issues without manual intervention.

## Features

- Real-time monitoring of CPU, Memory, Disk, and Network metrics
- Multi-level alerting (Warning at 80%, Critical at 90%)
- Automated instance recovery via Lambda
- Email notifications for all events
- Infrastructure as Code using Terraform
- CloudWatch Dashboard for visualization

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed system design.

## Prerequisites

- AWS Account with appropriate permissions
- Terraform >= 1.0
- AWS CLI configured
- SSH key pair for EC2 access

## Quick Start

### 1. Clone the Repository
```bash
git clone https://github.com/yourusername/aws-monitoring-automation.git
cd aws-monitoring-automation
```

### 2. Configure Variables

Edit `terraform.tfvars`:
```hcl
alert_email = "your-email@example.com"
```

### 3. Deploy Infrastructure
```bash
terraform init
terraform plan
terraform apply
```

### 4. Confirm SNS Subscription

Check your email and confirm the SNS subscription to receive alerts.

### 5. Access Dashboard

After deployment, Terraform outputs the CloudWatch Dashboard URL.

## Project Structure
```
aws-monitoring-automation/
├── main.tf                 # Provider and EC2 instance
├── alarm.tf               # CloudWatch alarms (warning level)
├── auto_healing.tf        # Lambda and critical alarms
├── dashboard.tf           # CloudWatch dashboard
├── variables.tf           # Input variables
├── terraform.tfvars       # Variable values
├── lambda/
│   └── auto_remediation.py  # Auto-healing Lambda function
├── ARCHITECTURE.md        # System architecture
└── README.md             # This file
```

## Monitoring Metrics

### AWS Native Metrics
- CPU Utilization
- Network In/Out
- Disk Read/Write Operations

### CloudWatch Agent Metrics
- Memory Usage Percentage
- Disk Usage Percentage
- CPU Usage (Active/Idle breakdown)

## Alarm Configuration

### Warning Alarms (Notification Only)
- **HighCPUUtilization**: CPU > 80% for 10 minutes
- **high-memory**: Memory > 80% for 10 minutes
- **high-disk-usage**: Disk > 80% for 10 minutes

### Critical Alarms (Auto-Healing)
- **CriticalCPU-AutoHeal**: CPU > 90% for 10 minutes → Reboots instance
- **CriticalMemory-AutoHeal**: Memory > 90% for 10 minutes → Reboots instance

## Testing Auto-Healing

SSH into the EC2 instance and generate high CPU load:
```bash
# Generate CPU load for 15 minutes
timeout 900 dd if=/dev/zero of=/dev/null &
timeout 900 dd if=/dev/zero of=/dev/null &
```

Monitor the process:
1. Wait 10-15 minutes for alarm to trigger
2. Check email for notifications
3. Observe instance reboot in EC2 console
4. View Lambda execution logs

## Monitoring Lambda Logs
```bash
aws logs tail /aws/lambda/auto_heal_ec2 --follow
```

## Cost Estimate

Approximate monthly costs (us-east-1):
- EC2 t3.micro: ~$7.50
- CloudWatch metrics: ~$3.00
- CloudWatch alarms: ~$1.00
- Lambda executions: <$0.20
- SNS notifications: <$0.50

**Total: ~$12/month**

## Cleanup

To destroy all resources:
```bash
terraform destroy
```

Type `yes` when prompted.

## Security Considerations

- Lambda has minimal IAM permissions (only reboot instances)
- SNS topics are private
- CloudWatch logs retained for 30 days
- No hardcoded credentials

## Improvements & Roadmap

- [ ] Add auto-scaling based on metrics
- [ ] Implement instance replacement instead of reboot
- [ ] Add Slack/PagerDuty integration
- [ ] Multi-region support
- [ ] Add database monitoring
- [ ] Custom metric collection

## Troubleshooting

### CloudWatch Agent Not Running
```bash
sudo systemctl status amazon-cloudwatch-agent
sudo systemctl restart amazon-cloudwatch-agent
```

### Metrics Not Appearing

- Verify IAM role attached to EC2 instance
- Check CloudWatch Agent logs: `/opt/aws/amazon-cloudwatch-agent/logs/`
- Ensure security group allows outbound HTTPS

### Lambda Not Triggering

- Check SNS topic subscription
- Verify Lambda execution role permissions
- Review CloudWatch Logs for errors

## Contributing

Contributions welcome! Please open an issue or submit a pull request.

## License

MIT License - See LICENSE file for details

## Author

Your Name
- GitHub: [@yourusername](https://github.com/yourusername)
- LinkedIn: [Your Profile](https://linkedin.com/in/yourprofile)
- Email: your-email@example.com

## Acknowledgments

- AWS Documentation
- Terraform AWS Provider
- CloudWatch Agent Configuration Guide

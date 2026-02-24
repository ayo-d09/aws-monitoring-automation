# Architecture Overview

## Auto-Healing Flow
```
┌─────────────┐
│   EC2       │
│  Instance   │
└──────┬──────┘
       │
       │ Metrics (CPU, Memory, Disk)
       ▼
┌─────────────────────┐
│  CloudWatch Agent   │
└──────────┬──────────┘
           │
           │ Send Metrics
           ▼
┌─────────────────────┐
│   CloudWatch        │
│   Metrics           │
└──────────┬──────────┘
           │
           │ Evaluate Thresholds
           ▼
┌─────────────────────┐
│  CloudWatch Alarm   │
│  (CPU > 90%)        │
└──────────┬──────────┘
           │
           │ Trigger on ALARM state
           ▼
┌─────────────────────┐
│   SNS Topic         │
└──────────┬──────────┘
           │
           ├──────────────┐
           │              │
           ▼              ▼
    ┌──────────┐   ┌──────────┐
    │  Lambda  │   │  Email   │
    │ Function │   │  Alert   │
    └────┬─────┘   └──────────┘
         │
         │ Reboot Instance
         ▼
    ┌──────────┐
    │   EC2    │
    │  Reboot  │
    └──────────┘
```

## Components

1. **EC2 Instance**: Target server being monitored
2. **CloudWatch Agent**: Collects detailed metrics (Memory, Disk)
3. **CloudWatch Metrics**: Stores and displays monitoring data
4. **CloudWatch Alarms**: Monitors thresholds and triggers actions
5. **SNS Topic**: Routes alarm notifications
6. **Lambda Function**: Executes auto-healing (reboot instance)
7. **Email Alerts**: Notifies administrators

## Alarm Thresholds

| Metric | Warning | Critical (Auto-Heal) |
|--------|---------|---------------------|
| CPU    | 80%     | 90%                 |
| Memory | 80%     | 90%                 |
| Disk   | 80%     | N/A                 |

## Tech Stack

- **Infrastructure**: Terraform
- **Monitoring**: AWS CloudWatch, CloudWatch Agent
- **Auto-Healing**: AWS Lambda (Python 3.11)
- **Notifications**: AWS SNS
- **Compute**: AWS EC2 (Amazon Linux 2)

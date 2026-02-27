import boto3
import json
import os
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ec2 = boto3.client('ec2')
sns  = boto3.client('sns')

def lambda_handler(event, context):
    """
    Auto-remediation Lambda:
    - Reboots EC2 instance when CloudWatch alarm goes to ALARM state
    - Sends notification via SNS (if topic ARN is configured)
    """
    try:
        # ── Parse SNS message from CloudWatch ───────────────────────────────
        if 'Records' not in event or not event['Records']:
            raise ValueError("No SNS records found in event")

        sns_message = event['Records'][0]['Sns']['Message']
        message = json.loads(sns_message)

        alarm_name       = message.get('AlarmName', 'Unknown')
        new_state        = message.get('NewStateValue')
        reason           = message.get('NewStateReason', 'No reason provided')
        state_change_time = message.get('StateChangeTime', 'Unknown')

        # Extract instance ID from dimensions
        instance_id = None
        for dim in message.get('Trigger', {}).get('Dimensions', []):
            if dim.get('name') == 'InstanceId':
                instance_id = dim.get('value')
                break

        if not instance_id:
            logger.error(f"No InstanceId found in alarm dimensions. Alarm: {alarm_name}")
            return {'statusCode': 400, 'body': 'No InstanceId found in alarm'}

        logger.info(f"Processing alarm: {alarm_name} | State: {new_state} | Instance: {instance_id}")

        # Only act on ALARM state (ignore OK / INSUFFICIENT_DATA)
        if new_state != 'ALARM':
            logger.info(f"Skipping action - state is {new_state}, not ALARM")
            return {
                'statusCode': 200,
                'body': json.dumps(f"Skipped - state is {new_state}")
            }

        # ── Check current instance state ────────────────────────────────────
        try:
            resp = ec2.describe_instances(InstanceIds=[instance_id])
            reservations = resp.get('Reservations', [])
            if not reservations or not reservations[0].get('Instances'):
                raise ValueError(f"Instance {instance_id} not found")

            instance = reservations[0]['Instances'][0]
            state    = instance['State']['Name']
            tags     = {t['Key']: t['Value'] for t in instance.get('Tags', [])}

            logger.info(f"Instance {instance_id} current state: {state}")

            if state != 'running':
                logger.warning(f"Instance {instance_id} is {state} → skipping reboot")
                return {
                    'statusCode': 200,
                    'body': json.dumps(f"Skipped - instance is {state}")
                }

        except ec2.exceptions.ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'InvalidInstanceID.NotFound':
                logger.error(f"Instance {instance_id} does not exist")
                return {'statusCode': 404, 'body': 'Instance not found'}
            raise

        # ── Perform reboot ──────────────────────────────────────────────────
        logger.info(f"Rebooting instance {instance_id}")
        ec2.reboot_instances(InstanceIds=[instance_id])

        # ── Optional: Send notification ─────────────────────────────────────
        topic_arn = os.environ.get('SNS_TOPIC_ARN')
        if topic_arn:
            try:
                subject = f"[Auto-Heal] {instance_id} Rebooted – {alarm_name}"
                body = (
                    f"Auto-healing action taken\n\n"
                    f"• Instance:     {instance_id}\n"
                    f"• Name/Tag:     {tags.get('Name', '—')}\n"
                    f"• Alarm:        {alarm_name}\n"
                    f"• Triggered by: {reason}\n"
                    f"• Time:         {state_change_time}\n\n"
                    f"Action: EC2 instance reboot initiated\n"
                    f"Expected recovery: 2–5 minutes"
                )

                sns.publish(
                    TopicArn=topic_arn,
                    Subject=subject,
                    Message=body
                )
                logger.info("SNS notification sent")
            except Exception as e:
                logger.error(f"Failed to send SNS notification: {str(e)}", exc_info=True)

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f"Reboot initiated for instance {instance_id}",
                'alarm': alarm_name
            })
        }

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in SNS message: {str(e)}")
        return {'statusCode': 400, 'body': 'Invalid SNS message format'}

    except Exception as e:
        logger.exception("Unexpected error in auto-remediation")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
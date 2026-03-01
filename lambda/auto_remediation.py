import boto3  # type: ignore
import json
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from botocore.exceptions import ClientError  # type: ignore

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ec2 = boto3.client('ec2')
sns = boto3.client('sns')
ssm = boto3.client('ssm')


try:
    COOLDOWN_MINUTES = int(os.environ.get('COOLDOWN_MINUTES', 15))
except ValueError:
    logger.warning("Invalid COOLDOWN_MINUTES env var; defaulting to 15")
    COOLDOWN_MINUTES = 15

SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN')


def get_last_reboot_time(instance_id: str) -> Optional[datetime]:
    param_name = f"/auto-remediation/last-reboot/{instance_id}"
    try:
        response = ssm.get_parameter(Name=param_name)
        timestamp_str = response['Parameter']['Value']
        parsed_time = datetime.fromisoformat(timestamp_str)
        if parsed_time.tzinfo is None:
            logger.warning(
                "SSM reboot timestamp for %s had no timezone; assuming UTC", instance_id)
            parsed_time = parsed_time.replace(tzinfo=timezone.utc)
        return parsed_time
    except ssm.exceptions.ParameterNotFound:
        return None
    except ValueError as e:
        logger.warning("Invalid timestamp format in SSM for %s: %s", instance_id, str(e))
        return None
    except ClientError as e:
        logger.warning("Could not read SSM parameter for %s: %s", instance_id, str(e))
        return None


def set_last_reboot_time(instance_id: str) -> None:
    param_name = f"/auto-remediation/last-reboot/{instance_id}"
    try:
        ssm.put_parameter(
            Name=param_name,
            Value=datetime.now(timezone.utc).isoformat(),
            Type='String',
            Overwrite=True
        )
    except ClientError as e:
        logger.warning("Could not write SSM parameter for %s: %s", instance_id, str(e))


def is_in_cooldown(instance_id: str) -> bool:
   
    last_reboot = get_last_reboot_time(instance_id)
    if last_reboot is None:
        return False
    elapsed = datetime.now(timezone.utc) - last_reboot
    in_cooldown = elapsed < timedelta(minutes=COOLDOWN_MINUTES)
    if in_cooldown:
        logger.warning(
            "Instance %s is in cooldown. Last reboot: %s | Elapsed: %d min | Cooldown: %d min",
            instance_id,
            last_reboot.isoformat(),
            int(elapsed.total_seconds() // 60),
            COOLDOWN_MINUTES
        )
    return in_cooldown


def get_instance_info(instance_id: str) -> Optional[dict]:
    try:
        resp = ec2.describe_instances(InstanceIds=[instance_id])
        reservations = resp.get('Reservations', [])
        if not reservations or not reservations[0].get('Instances'):
            logger.error("Instance %s not found in response", instance_id)
            return None
        instance = reservations[0]['Instances'][0]
        return {
            'state': instance['State']['Name'],
            'tags': {t['Key']: t['Value'] for t in instance.get('Tags', [])}
        }
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'InvalidInstanceID.NotFound':
            logger.error("Instance %s does not exist", instance_id)
            return None
        logger.error("Unexpected EC2 error for %s: %s", instance_id, str(e))
        raise


def reboot_instance(instance_id: str) -> bool:
    try:
        ec2.reboot_instances(InstanceIds=[instance_id])
        logger.info("Reboot command accepted for instance %s", instance_id)
        set_last_reboot_time(instance_id)
        return True
    except Exception as e:
        logger.error("Failed to reboot %s: %s", instance_id, str(e), exc_info=True)
        return False


def send_notification(instance_id: str, tags: dict, alarm_name: str,
                      reason: str, state_change_time: str, success: bool) -> None:
    if not SNS_TOPIC_ARN:
        logger.info("SNS_TOPIC_ARN not set - skipping notification")
        return

    status = "Rebooted" if success else "Reboot FAILED"
  
    subject = f"[Auto-Heal] {instance_id} {status} – {alarm_name}"[:100]
    body = (
        f"Auto-healing action {'succeeded' if success else 'FAILED'}\n\n"
        f"• Instance:     {instance_id}\n"
        f"• Name/Tag:     {tags.get('Name', '—')}\n"
        f"• Alarm:        {alarm_name}\n"
        f"• Triggered by: {reason}\n"
        f"• Time:         {state_change_time}\n\n"
        f"Action: EC2 instance reboot {'initiated' if success else 'failed — manual intervention required'}\n"
        + ("Expected recovery: 2–5 minutes" if success else "")
    )

    try:
        sns.publish(TopicArn=SNS_TOPIC_ARN, Subject=subject, Message=body)
        logger.info("SNS notification sent")
    except ClientError as e:
        logger.error("Failed to send SNS notification: %s", str(e), exc_info=True)


def process_record(record: dict) -> dict:
    """Process a single SNS record and perform remediation if needed."""
    try:
        sns_message = record['Sns']['Message']
        message = json.loads(sns_message)
    except (KeyError, json.JSONDecodeError) as e:
        logger.error("Failed to parse SNS record: %s", str(e))
        return {'statusCode': 400, 'body': 'Invalid SNS message format'}

    alarm_name = message.get('AlarmName', 'Unknown')
    new_state = message.get('NewStateValue')
    reason = message.get('NewStateReason', 'No reason provided')
    state_change_time = message.get('StateChangeTime', 'Unknown')

    instance_id = None
    for dim in message.get('Trigger', {}).get('Dimensions', []):

        raw_name = dim.get('name')
        name = raw_name if raw_name is not None else dim.get('Name')
        if name == 'InstanceId':
            raw_value = dim.get('value')
            instance_id = raw_value if raw_value is not None else dim.get('Value')
            break

    if not instance_id:
        logger.error("No InstanceId found in alarm dimensions. Alarm: %s", alarm_name)
        return {'statusCode': 400, 'body': 'No InstanceId found in alarm'}

    logger.info("Processing alarm: %s | State: %s | Instance: %s",
                alarm_name, new_state, instance_id)

    if new_state != 'ALARM':
        logger.info("Skipping — state is %s, not ALARM", new_state)
        return {'statusCode': 200, 'body': f"Skipped - state is {new_state}"}

    if is_in_cooldown(instance_id):
        return {'statusCode': 200, 'body': 'Skipped - cooldown period active'}

    info = get_instance_info(instance_id)
    if info is None:
        return {'statusCode': 404, 'body': 'Instance not found'}

    tags = info['tags']
    state = info['state']
    logger.info("Instance %s current state: %s", instance_id, state)

    if state != 'running':
        logger.warning("Instance %s is %s — skipping reboot", instance_id, state)
        return {'statusCode': 200, 'body': f"Skipped - instance is {state}"}

    success = reboot_instance(instance_id)
    send_notification(instance_id, tags, alarm_name, reason, state_change_time, success)

    if not success:
        return {'statusCode': 500, 'body': 'Reboot failed'}

    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': f"Reboot initiated for instance {instance_id}",
            'alarm': alarm_name
        })
    }


def lambda_handler(event, _):
    """
    Auto-remediation Lambda entry point.
    Processes all SNS records in the event.
    """
    if 'Records' not in event or not event['Records']:
        logger.error("No SNS records found in event")
        return {'statusCode': 400, 'body': 'No SNS records found'}

    results = []
    for record in event['Records']:
        try:
            result = process_record(record)
            results.append(result)
        except Exception as e:
            logger.exception("Error processing record: %s", str(e))
            results.append({'statusCode': 500, 'body': str(e)})

  
    overall_status = 200 if all(r['statusCode'] == 200 for r in results) else 500
    return {'statusCode': overall_status, 'body': json.dumps(results)}

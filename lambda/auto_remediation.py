import boto3
import json
import os
import logging
from datetime import datetime, timezone, timedelta
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ec2 = boto3.client('ec2')
sns = boto3.client('sns')
ssm = boto3.client('ssm')

COOLDOWN_MINUTES = int(os.environ.get('COOLDOWN_MINUTES', 15))
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN')


def get_last_reboot_time(instance_id: str) -> datetime | None:
    """Retrieve last reboot timestamp from SSM Parameter Store."""
    param_name = f"/auto-remediation/last-reboot/{instance_id}"
    try:
        response = ssm.get_parameter(Name=param_name)
        timestamp_str = response['Parameter']['Value']
        return datetime.fromisoformat(timestamp_str)
    except ssm.exceptions.ParameterNotFound:
        return None
    except ClientError as e:
        logger.warning(f"Could not read SSM parameter for {instance_id}: {str(e)}")
        return None


def set_last_reboot_time(instance_id: str) -> None:
    """Store current timestamp in SSM Parameter Store as cooldown marker."""
    param_name = f"/auto-remediation/last-reboot/{instance_id}"
    try:
        ssm.put_parameter(
            Name=param_name,
            Value=datetime.now(timezone.utc).isoformat(),
            Type='String',
            Overwrite=True
        )
    except ClientError as e:
        logger.warning(f"Could not write SSM parameter for {instance_id}: {str(e)}")


def is_in_cooldown(instance_id: str) -> bool:
    """Return True if instance was rebooted within the cooldown window."""
    last_reboot = get_last_reboot_time(instance_id)
    if last_reboot is None:
        return False
    elapsed = datetime.now(timezone.utc) - last_reboot
    in_cooldown = elapsed < timedelta(minutes=COOLDOWN_MINUTES)
    if in_cooldown:
        logger.warning(
            f"Instance {instance_id} is in cooldown. "
            f"Last reboot: {last_reboot.isoformat()} | "
            f"Elapsed: {int(elapsed.total_seconds() // 60)} min | "
            f"Cooldown: {COOLDOWN_MINUTES} min"
        )
    return in_cooldown


def get_instance_info(instance_id: str) -> dict | None:
    """
    Describe EC2 instance and return state + tags.
    Returns None if instance does not exist.
    """
    try:
        resp = ec2.describe_instances(InstanceIds=[instance_id])
        reservations = resp.get('Reservations', [])
        if not reservations or not reservations[0].get('Instances'):
            logger.error(f"Instance {instance_id} not found in response")
            return None
        instance = reservations[0]['Instances'][0]
        return {
            'state': instance['State']['Name'],
            'tags': {t['Key']: t['Value'] for t in instance.get('Tags', [])}
        }
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'InvalidInstanceID.NotFound':
            logger.error(f"Instance {instance_id} does not exist")
            return None
        logger.error(f"Unexpected EC2 error for {instance_id}: {str(e)}")
        raise


def reboot_instance(instance_id: str) -> bool:
    """
    Reboot EC2 instance.
    Returns True on success, False on failure.
    """
    try:
        ec2.reboot_instances(InstanceIds=[instance_id])
        logger.info(f"Reboot command accepted for instance {instance_id}")
        set_last_reboot_time(instance_id)
        return True
    except ClientError as e:
        logger.error(f"Failed to reboot {instance_id}: {str(e)}", exc_info=True)
        return False


def send_notification(instance_id: str, tags: dict, alarm_name: str,
                      reason: str, state_change_time: str, success: bool) -> None:
    """Send SNS notification summarizing the remediation action."""
    if not SNS_TOPIC_ARN:
        logger.info("SNS_TOPIC_ARN not set - skipping notification")
        return

    status = "Rebooted" if success else "Reboot FAILED"
    subject = f"[Auto-Heal] {instance_id} {status} – {alarm_name}"
    body = (
        f"Auto-healing action {'succeeded' if success else 'FAILED'}\n\n"
        f"• Instance:     {instance_id}\n"
        f"• Name/Tag:     {tags.get('Name', '—')}\n"
        f"• Alarm:        {alarm_name}\n"
        f"• Triggered by: {reason}\n"
        f"• Time:         {state_change_time}\n\n"
        f"Action: EC2 instance reboot {'initiated' if success else 'failed — manual intervention required'}\n"
        + (f"Expected recovery: 2–5 minutes" if success else "")
    )

    try:
        sns.publish(TopicArn=SNS_TOPIC_ARN, Subject=subject, Message=body)
        logger.info("SNS notification sent")
    except ClientError as e:
        logger.error(f"Failed to send SNS notification: {str(e)}", exc_info=True)


def process_record(record: dict) -> dict:
    """Process a single SNS record and perform remediation if needed."""
    tags = {}

    try:
        sns_message = record['Sns']['Message']
        message = json.loads(sns_message)
    except (KeyError, json.JSONDecodeError) as e:
        logger.error(f"Failed to parse SNS record: {str(e)}")
        return {'statusCode': 400, 'body': 'Invalid SNS message format'}

    alarm_name        = message.get('AlarmName', 'Unknown')
    new_state         = message.get('NewStateValue')
    reason            = message.get('NewStateReason', 'No reason provided')
    state_change_time = message.get('StateChangeTime', 'Unknown')

    instance_id = None
    for dim in message.get('Trigger', {}).get('Dimensions', []):
        if dim.get('name') == 'InstanceId':
            instance_id = dim.get('value')
            break

    if not instance_id:
        logger.error(f"No InstanceId found in alarm dimensions. Alarm: {alarm_name}")
        return {'statusCode': 400, 'body': 'No InstanceId found in alarm'}

    logger.info(f"Processing alarm: {alarm_name} | State: {new_state} | Instance: {instance_id}")


    if new_state != 'ALARM':
        logger.info(f"Skipping — state is {new_state}, not ALARM")
        return {'statusCode': 200, 'body': f"Skipped - state is {new_state}"}

    if is_in_cooldown(instance_id):
        return {'statusCode': 200, 'body': 'Skipped - cooldown period active'}


    info = get_instance_info(instance_id)
    if info is None:
        return {'statusCode': 404, 'body': 'Instance not found'}

    tags  = info['tags']
    state = info['state']
    logger.info(f"Instance {instance_id} current state: {state}")

    if state != 'running':
        logger.warning(f"Instance {instance_id} is {state} — skipping reboot")
        return {'statusCode': 200, 'body': f"Skipped - instance is {state}"}

    # Reboot
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


def lambda_handler(event, context):
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
            logger.exception(f"Unexpected error processing record: {str(e)}")
            results.append({'statusCode': 500, 'body': str(e)})


    overall_status = 500 if any(r['statusCode'] == 500 for r in results) else 200
    return {'statusCode': overall_status, 'body': json.dumps(results)}
import boto3
import json
import os
import logging
from datetime import datetime, timezone, timedelta

# Set up logging so we can see what's happening
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Create connections to AWS services
ec2 = boto3.client('ec2')      # For working with EC2 instances
sns = boto3.client('sns')       # For sending notifications
ssm = boto3.client('ssm')       # For storing reboot history

# Get settings from environment variables (set in Lambda)
try:
    COOLDOWN_MINUTES = int(os.environ.get('COOLDOWN_MINUTES', '15'))
except:
    COOLDOWN_MINUTES = 15  # Default to 15 minutes if setting is wrong

SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN')  # Where to send notifications

def get_last_reboot_time(instance_id):
    """
    Check when this instance was last rebooted by our automation.
    Returns None if never rebooted or if we can't find the info.
    """
    # SSM Parameter path where we store reboot times
    param_name = f"/auto-remediation/last-reboot/{instance_id}"
    
    try:
        # Try to get the stored reboot time
        response = ssm.get_parameter(Name=param_name)
        timestamp_str = response['Parameter']['Value']
        
        # Convert the stored text into a datetime object
        reboot_time = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        
        # Make sure it has timezone info (assume UTC if not)
        if reboot_time.tzinfo is None:
            reboot_time = reboot_time.replace(tzinfo=timezone.utc)
            
        return reboot_time
        
    except ssm.exceptions.ParameterNotFound:
        # No reboot history found - this is normal for first time
        return None
    except Exception as e:
        # Something else went wrong, but we can continue
        logger.warning(f"Could not read reboot time for {instance_id}: {str(e)}")
        return None

def set_last_reboot_time(instance_id):
    """
    Store the current time as the last reboot time for this instance.
    """
    param_name = f"/auto-remediation/last-reboot/{instance_id}"
    
    try:
        # Save current time to SSM Parameter Store
        current_time = datetime.now(timezone.utc).isoformat()
        ssm.put_parameter(
            Name=param_name,
            Value=current_time,
            Type='String',
            Overwrite=True  # Update if it already exists
        )
        logger.info(f"Updated last reboot time for instance {instance_id}")
    except Exception as e:
        # Log error but don't stop the reboot
        logger.warning(f"Could not save reboot time for {instance_id}: {str(e)}")

def is_in_cooldown(instance_id):
    """
    Check if we should wait before rebooting this instance again.
    Returns True if we should NOT reboot, False if it's OK to reboot.
    """
    last_reboot = get_last_reboot_time(instance_id)
    
    # If never rebooted before, definitely not in cooldown
    if last_reboot is None:
        return False
    
    # Calculate how long since last reboot
    time_since_reboot = datetime.now(timezone.utc) - last_reboot
    minutes_since = time_since_reboot.total_seconds() / 60
    
    # Check if we're still in the cooldown period
    if minutes_since < COOLDOWN_MINUTES:
        logger.warning(
            f"Instance {instance_id} was rebooted {int(minutes_since)} minutes ago. "
            f"Waiting {COOLDOWN_MINUTES} minutes between reboots."
        )
        return True
    
    return False

def get_instance_details(instance_id):
    """
    Get information about an EC2 instance.
    Returns a dictionary with instance details, or None if instance doesn't exist.
    """
    try:
        # Ask EC2 for instance details
        response = ec2.describe_instances(InstanceIds=[instance_id])
        
        # Navigate through the response to get instance data
        reservations = response.get('Reservations', [])
        if not reservations or not reservations[0].get('Instances'):
            logger.error(f"Instance {instance_id} not found")
            return None
            
        instance = reservations[0]['Instances'][0]
        
        # Get tags (like Name) as a simple dictionary
        tags = {}
        for tag in instance.get('Tags', []):
            tags[tag['Key']] = tag['Value']
        
        # Return the important information
        return {
            'state': instance['State']['Name'],
            'tags': tags,
            'name': tags.get('Name', 'Unknown'),  # Get Name tag, or 'Unknown' if not set
            'type': instance['InstanceType'],
            'launch_time': instance['LaunchTime']
        }
        
    except Exception as e:
        # Check if instance doesn't exist
        if 'InvalidInstanceID.NotFound' in str(e):
            logger.error(f"Instance {instance_id} does not exist")
            return None
        else:
            # Some other error occurred
            logger.error(f"Error getting instance info: {str(e)}")
            raise

def reboot_instance(instance_id):
    """
    Send a reboot command to an EC2 instance.
    Returns True if reboot command was sent, False if it failed.
    """
    try:
        # Send the reboot command
        ec2.reboot_instances(InstanceIds=[instance_id])
        logger.info(f"Reboot command sent to instance {instance_id}")
        
        # Record when we did this reboot
        set_last_reboot_time(instance_id)
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to reboot {instance_id}: {str(e)}")
        return False

def send_notification(instance_id, instance_name, alarm_name, reason, state_change_time, success):
    """
    Send an SNS notification about what we did.
    Skips sending if SNS_TOPIC_ARN is not set.
    """
    # Skip if no SNS topic configured
    if not SNS_TOPIC_ARN:
        logger.info("No SNS topic configured - skipping notification")
        return
    
    # Create subject line (keep it short)
    status = "SUCCESS" if success else "FAILED"
    subject = f"[Auto-Heal] {status} - {instance_name} ({instance_id})"
    
    # Create the message body
    body = f"""
Auto-healing Action: {status}
{'='*50}

INSTANCE:
• Instance ID: {instance_id}
• Instance Name: {instance_name}

ALARM:
• Alarm Name: {alarm_name}
• Reason: {reason}
• Time: {state_change_time}

ACTION: EC2 instance reboot was {'initiated' if success else 'FAILED'}
{f'• Expected recovery: 2-5 minutes' if success else '• Manual intervention may be required'}
"""
    
    try:
        # Send the notification
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=subject[:100],  # SNS subjects have a 100 character limit
            Message=body
        )
        logger.info("Notification sent successfully")
    except Exception as e:
        logger.error(f"Failed to send notification: {str(e)}")

def lambda_handler(event, context):
    """
    Main function that AWS Lambda calls when this script runs.
    event: The SNS message that triggered this function
    context: Information about the Lambda environment
    """
    logger.info("="*50)
    logger.info("Auto-remediation function started")
    
    # Check if we have any records to process
    if 'Records' not in event or not event['Records']:
        logger.error("No SNS records found in event")
        return {
            'statusCode': 400,
            'body': json.dumps('No SNS records found')
        }
    
    # Process each record (usually just one)
    for record in event['Records']:
        try:
            # Step 1: Parse the SNS message
            sns_message = record['Sns']['Message']
            message = json.loads(sns_message)
            
            # Step 2: Get alarm information
            alarm_name = message.get('AlarmName', 'Unknown')
            new_state = message.get('NewStateValue')
            reason = message.get('NewStateReason', 'No reason provided')
            state_change_time = message.get('StateChangeTime', 'Unknown')
            
            logger.info(f"Alarm: {alarm_name}")
            logger.info(f"State: {new_state}")
            logger.info(f"Reason: {reason}")
            
            # Step 3: Only act when alarm goes into ALARM state
            if new_state != 'ALARM':
                logger.info(f"State is {new_state} - no action needed")
                continue
            
            # Step 4: Find the instance ID from the alarm
            instance_id = None
            trigger = message.get('Trigger', {})
            dimensions = trigger.get('Dimensions', [])
            
            for dim in dimensions:
                # Look for the InstanceId dimension
                dim_name = dim.get('name') or dim.get('Name')
                if dim_name == 'InstanceId':
                    instance_id = dim.get('value') or dim.get('Value')
                    break
            
            if not instance_id:
                logger.error(f"Could not find Instance ID in alarm: {alarm_name}")
                continue
            
            logger.info(f"Instance ID: {instance_id}")
            
            # Step 5: Check cooldown period
            if is_in_cooldown(instance_id):
                logger.info(f"Instance {instance_id} is in cooldown - skipping reboot")
                continue
            
            # Step 6: Get instance details
            instance_details = get_instance_details(instance_id)
            if not instance_details:
                logger.error(f"Could not get details for instance {instance_id}")
                continue
            
            # Step 7: Check if instance is running
            if instance_details['state'] != 'running':
                logger.info(f"Instance is {instance_details['state']} - only running instances can be rebooted")
                continue
            
            # Step 8: Reboot the instance
            instance_name = instance_details['name']
            logger.info(f"Attempting to reboot {instance_name} ({instance_id})")
            
            reboot_successful = reboot_instance(instance_id)
            
            # Step 9: Send notification about what we did
            send_notification(
                instance_id,
                instance_name,
                alarm_name,
                reason,
                state_change_time,
                reboot_successful
            )
            
            if reboot_successful:
                logger.info(f"Successfully initiated reboot for {instance_id}")
            else:
                logger.error(f"Failed to reboot {instance_id}")
                
        except Exception as e:
            # Catch any unexpected errors so we can log them
            logger.error(f"Error processing record: {str(e)}")
            logger.exception("Full error details:")
    
    logger.info("Auto-remediation function completed")
    
    return {
        'statusCode': 200,
        'body': json.dumps('Processing complete')
    }
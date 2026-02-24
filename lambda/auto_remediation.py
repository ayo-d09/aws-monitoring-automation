cat > auto_remediation.py << 'EOF'
import boto3
import json
import os

ec2 = boto3.client('ec2')
sns = boto3.client('sns')

def lambda_handler(event, context):
    """
    Auto-remediation Lambda function
    Reboots EC2 instance when CloudWatch alarm triggers
    """
    print(f"Event received: {json.dumps(event)}")
    
    # Parse SNS message from CloudWatch
    message = json.loads(event['Records'][0]['Sns']['Message'])
    alarm_name = message['AlarmName']
    new_state = message['NewStateValue']
    reason = message['NewStateReason']
    
    # Extract instance ID from dimensions
    instance_id = None
    for dimension in message['Trigger']['Dimensions']:
        if dimension['name'] == 'InstanceId':
            instance_id = dimension['value']
            break
    
    if not instance_id:
        print("ERROR: No instance ID found in alarm")
        return {'statusCode': 400, 'body': 'No instance ID'}
    
    print(f"Alarm: {alarm_name}")
    print(f"State: {new_state}")
    print(f"Instance: {instance_id}")
    print(f"Reason: {reason}")
    
    # Only take action if alarm state is ALARM
    if new_state == 'ALARM':
        try:
            # Check instance state
            response = ec2.describe_instances(InstanceIds=[instance_id])
            instance_state = response['Reservations'][0]['Instances'][0]['State']['Name']
            
            print(f"Current instance state: {instance_state}")
            
            if instance_state == 'running':
                # Reboot the instance
                print(f"Rebooting instance {instance_id}")
                ec2.reboot_instances(InstanceIds=[instance_id])
                
                # Send notification
                sns_topic = os.environ.get('SNS_TOPIC_ARN')
                if sns_topic:
                    sns.publish(
                        TopicArn=sns_topic,
                        Subject=f'Auto-Healing: {instance_id} Rebooted',
                        Message=f"""Auto-healing triggered

Instance: {instance_id}
Alarm: {alarm_name}
Action: Instance rebooted
Reason: {reason}
Time: {message['StateChangeTime']}

The instance will be back online in a few minutes.
"""
                    )
                
                return {
                    'statusCode': 200,
                    'body': json.dumps(f'Instance {instance_id} rebooted
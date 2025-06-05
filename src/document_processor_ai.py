import json
import boto3
import os
import uuid
import urllib.parse
from datetime import datetime

# Initialize AWS clients
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
sns_client = boto3.client('sns')
bedrock_runtime = boto3.client('bedrock-runtime')

# Get environment variables
TABLE_NAME = os.environ['TABLE_NAME']
TOPIC_ARN = os.environ['TOPIC_ARN']
INFERENCE_PROFILE = os.environ.get('INFERENCE_PROFILE', '')
MODEL_ID = os.environ.get('MODEL_ID', 'anthropic.claude-3-7-sonnet-20250219-v1:0')

# Define model-specific request formats
CLAUDE_FORMAT = {
    "anthropic_version": "bedrock-2023-05-31",
    "max_tokens": 4000,
    "temperature": 0.2,
    "messages": [
        {
            "role": "user",
            "content": "{prompt}"
        }
    ]
}

def lambda_handler(event, context):
    """
    Lambda function that processes documents uploaded to S3,
    generates a summary using DeepSeek-R1 on Amazon Bedrock,
    stores the summary in DynamoDB, and sends a notification.
    """
    try:
        print(f"Received event: {json.dumps(event)}")
        # Get bucket and object information from the event
        bucket = event['Records'][0]['s3']['bucket']['name']
        key = urllib.parse.unquote_plus(event['Records'][0]['s3']['object']['key'])
        
        print(f"Processing document: {key} from bucket: {bucket}")
        
        # Generate a unique document ID
        document_id = str(uuid.uuid4())
        
        # Get the document content from S3
        response = s3_client.get_object(Bucket=bucket, Key=key)
        document_content = response['Body'].read().decode('utf-8')
        
        print(f"Document content length: {len(document_content)} characters")
        
        # Try to generate summary with inference profile first
        summary = ""
        if INFERENCE_PROFILE:
            print("Attempting to generate summary using inference profile...")
            summary = generate_summary_with_bedrock(document_content)
        
        # If inference profile failed or wasn't provided, try direct model invocation
        if not summary or summary.startswith("Error") or summary.startswith("Unable"):
            print("Inference profile method failed or not available. Trying direct model invocation...")
            summary = generate_summary_direct(document_content)
        
        print(f"Summary generated, length: {len(summary)} characters")
        print(f"Summary preview: {summary[:100]}...")
        
        # Store the summary in DynamoDB
        store_summary(document_id, key, summary)
        
        # Send a notification
        send_notification(document_id, key)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Document processed successfully with AI summarization',
                'document_id': document_id,
                'summary_length': len(summary)
            })
        }
    except Exception as e:
        print(f"Error processing document: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'message': f'Error processing document: {str(e)}'
            })
        }

def generate_summary_with_bedrock(document_content):
    """
    Generate a summary of the document content using DeepSeek-R1 on Amazon Bedrock.
    """
    # Truncate document content if it's too long (Bedrock has token limits)
    max_chars = 24000  # Approximate limit for DeepSeek-R1
    if len(document_content) > max_chars:
        document_content = document_content[:max_chars] + "..."
    
    # Create the prompt for DeepSeek-R1
    prompt = f"""
    Please provide a comprehensive summary of the following document. 
    Focus on the main points, key findings, and important details.
    The summary should be well-structured and capture the essence of the document.
    
    DOCUMENT:
    {document_content}
    
    SUMMARY:
    """
    
    try:
        # Prepare the request payload for DeepSeek-R1
        # Note: Different models require different request formats
        request_body = {
            "prompt": prompt,
            "max_tokens": 1000,
            "temperature": 0.2,
            "top_p": 0.9
        }
        
        print("Request body:", json.dumps(request_body))
        
        # Invoke the DeepSeek-R1 model using inference profile if available
        if INFERENCE_PROFILE:
            print(f"Using inference profile: {INFERENCE_PROFILE}")
            response = bedrock_runtime.invoke_model(
                modelId=INFERENCE_PROFILE,
                body=json.dumps(request_body)
            )
            print("Response received from Bedrock using inference profile")
        else:
            # Fallback to direct model invocation (not recommended for production)
            print(f"Warning: Using direct model ID without inference profile: {MODEL_ID}")
            response = bedrock_runtime.invoke_model(
                modelId=MODEL_ID,
                body=json.dumps(request_body)
            )
            print("Response received from Bedrock using direct model ID")
        
        # Parse the response
        response_body = json.loads(response['body'].read())
        print("Response body:", json.dumps(response_body))
        
        # Try to extract the summary from various possible response formats
        summary = ""
        
        # Format 1: DeepSeek direct model format
        if 'generation' in response_body:
            summary = response_body.get('generation', '')
            print("Found summary in 'generation' field")
        
        # Format 2: Choices array format (like OpenAI/Claude)
        elif 'choices' in response_body and isinstance(response_body['choices'], list):
            for choice in response_body['choices']:
                if 'text' in choice and choice['text']:
                    summary = choice['text']
                    print("Found summary in 'choices[].text' field")
                    break
                elif 'message' in choice and 'content' in choice['message']:
                    summary = choice['message']['content']
                    print("Found summary in 'choices[].message.content' field")
                    break
        
        # Format 3: Completion format
        elif 'completion' in response_body:
            summary = response_body.get('completion', '')
            print("Found summary in 'completion' field")
        
        # Format 4: Content format
        elif 'content' in response_body:
            summary = response_body.get('content', '')
            print("Found summary in 'content' field")
        
        # Format 5: Text format
        elif 'text' in response_body:
            summary = response_body.get('text', '')
            print("Found summary in 'text' field")
        
        # Format 6: Output format
        elif 'output' in response_body:
            summary = response_body.get('output', '')
            print("Found summary in 'output' field")
        
        # If we still don't have a summary, try a different request format
        if not summary:
            print("No summary found in response, trying alternative request format")
            
            # Try a different request format (Claude/Anthropic style)
            alt_request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1000,
                "temperature": 0.2,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            }
            
            print("Alternative request body:", json.dumps(alt_request_body))
            
            try:
                alt_response = bedrock_runtime.invoke_model(
                    modelId=INFERENCE_PROFILE,
                    body=json.dumps(alt_request_body)
                )
                alt_response_body = json.loads(alt_response['body'].read())
                print("Alternative response body:", json.dumps(alt_response_body))
                
                if 'content' in alt_response_body:
                    summary = alt_response_body['content']
                elif 'choices' in alt_response_body and len(alt_response_body['choices']) > 0:
                    if 'message' in alt_response_body['choices'][0]:
                        summary = alt_response_body['choices'][0]['message'].get('content', '')
                    elif 'text' in alt_response_body['choices'][0]:
                        summary = alt_response_body['choices'][0]['text']
            except Exception as alt_error:
                print(f"Alternative request format failed: {str(alt_error)}")
        
        # If we still don't have a summary, use a fallback
        if not summary:
            print("Warning: Could not extract summary from response")
            summary = "The AI model was unable to generate a summary for this document. Please check the model configuration and try again."
        
        # Clean up the summary if needed
        summary = summary.strip()
        
        return summary
        
    except Exception as e:
        print(f"Error in generate_summary_with_bedrock: {str(e)}")
        # Return a fallback summary
        return f"Error generating summary: {str(e)}"

def store_summary(document_id, document_key, summary):
    """
    Store the document summary in DynamoDB.
    """
    table = dynamodb.Table(TABLE_NAME)
    
    item = {
        'DocumentId': document_id,
        'DocumentKey': document_key,
        'Summary': summary,
        'CreatedAt': datetime.now().isoformat(),
        'SummaryMethod': 'Claude 3.7 Sonnet'
    }
    
    table.put_item(Item=item)
    print(f"AI-generated summary stored in DynamoDB for document {document_id}")

def send_notification(document_id, document_key):
    """
    Send a notification via SNS.
    """
    message = {
        'document_id': document_id,
        'document_key': document_key,
        'message': 'AI-powered document summary is ready (using Claude 3.7 Sonnet)',
        'timestamp': datetime.now().isoformat()
    }
    
    sns_client.publish(
        TopicArn=TOPIC_ARN,
        Message=json.dumps(message),
        Subject='AI Document Summary Notification'
    )
    
    print(f"Notification sent for document {document_id}")
def generate_summary_direct(document_content):
    """
    Generate a summary using direct model invocation as a fallback method.
    This bypasses the inference profile and directly calls the Claude model.
    """
    # Truncate document content if it's too long
    max_chars = 150000  # Claude 3.7 can handle larger contexts
    if len(document_content) > max_chars:
        document_content = document_content[:max_chars] + "..."
    
    # Create the prompt for Claude
    prompt = f"""
    Please provide a comprehensive summary of the following document. 
    Focus on the main points, key findings, and important details.
    The summary should be well-structured and capture the essence of the document.
    
    DOCUMENT:
    {document_content}
    
    SUMMARY:
    """
    
    try:
        # Use the Claude format
        request_body = CLAUDE_FORMAT.copy()
        request_body["messages"][0]["content"] = prompt
        
        print("Using direct model invocation with Claude model ID:", MODEL_ID)
        response = bedrock_runtime.invoke_model(
            modelId=MODEL_ID,
            body=json.dumps(request_body)
        )
        
        response_body = json.loads(response['body'].read())
        print("Direct model response type:", type(response_body))
        print("Direct model response content:", json.dumps(response_body))
        
        # Extract summary from Claude response format
        if 'content' in response_body and isinstance(response_body['content'], str):
            return response_body['content'].strip()
        elif 'content' in response_body and isinstance(response_body['content'], list):
            # Handle case where content is a list
            content_list = response_body['content']
            if content_list and len(content_list) > 0:
                # Join all elements if it's a list of strings
                if all(isinstance(item, str) for item in content_list):
                    return " ".join(content_list).strip()
                # Try to extract text from list of objects
                result = []
                for item in content_list:
                    if isinstance(item, dict) and 'text' in item:
                        result.append(item['text'])
                if result:
                    return " ".join(result).strip()
        elif 'choices' in response_body and len(response_body['choices']) > 0:
            if 'message' in response_body['choices'][0]:
                content = response_body['choices'][0]['message'].get('content', '')
                if isinstance(content, str):
                    return content.strip()
                elif isinstance(content, list):
                    # Handle case where content is a list
                    if all(isinstance(item, str) for item in content):
                        return " ".join(content).strip()
                    # Try to extract text from list of objects
                    result = []
                    for item in content:
                        if isinstance(item, dict) and 'text' in item:
                            result.append(item['text'])
                    if result:
                        return " ".join(result).strip()
            
        print("Unexpected response format:", json.dumps(response_body))
        return "Direct model invocation did not return expected response format."
    
    except Exception as e:
        print(f"Direct model invocation failed: {str(e)}")
        return f"Direct model invocation failed: {str(e)}"
def generate_summary_with_bedrock(document_content):
    """
    Generate a summary of the document content using an inference profile.
    """
    # Truncate document content if it's too long
    max_chars = 150000  # Claude 3.7 can handle larger contexts
    if len(document_content) > max_chars:
        document_content = document_content[:max_chars] + "..."
    
    # Create the prompt for Claude
    prompt = f"""
    Please provide a comprehensive summary of the following document. 
    Focus on the main points, key findings, and important details.
    The summary should be well-structured and capture the essence of the document.
    
    DOCUMENT:
    {document_content}
    
    SUMMARY:
    """
    
    try:
        # Use Claude format
        request_body = CLAUDE_FORMAT.copy()
        request_body["messages"][0]["content"] = prompt
        
        print(f"Using inference profile: {INFERENCE_PROFILE}")
        print("Request body (Claude format):", json.dumps(request_body))
        
        response = bedrock_runtime.invoke_model(
            modelId=INFERENCE_PROFILE,
            body=json.dumps(request_body)
        )
        
        response_body = json.loads(response['body'].read())
        print("Response body type:", type(response_body))
        print("Response body content:", json.dumps(response_body))
        
        # Try to extract summary from Claude format response
        if 'content' in response_body and isinstance(response_body['content'], str):
            return response_body['content'].strip()
        elif 'content' in response_body and isinstance(response_body['content'], list):
            # Handle case where content is a list
            content_list = response_body['content']
            if content_list and len(content_list) > 0:
                # Join all elements if it's a list of strings
                if all(isinstance(item, str) for item in content_list):
                    return " ".join(content_list).strip()
                # Try to extract text from list of objects
                result = []
                for item in content_list:
                    if isinstance(item, dict) and 'text' in item:
                        result.append(item['text'])
                if result:
                    return " ".join(result).strip()
        elif 'choices' in response_body and len(response_body['choices']) > 0:
            if 'message' in response_body['choices'][0]:
                content = response_body['choices'][0]['message'].get('content', '')
                if isinstance(content, str):
                    return content.strip()
                elif isinstance(content, list):
                    # Handle case where content is a list
                    if all(isinstance(item, str) for item in content):
                        return " ".join(content).strip()
                    # Try to extract text from list of objects
                    result = []
                    for item in content:
                        if isinstance(item, dict) and 'text' in item:
                            result.append(item['text'])
                    if result:
                        return " ".join(result).strip()
        
        print("Unexpected response format:", json.dumps(response_body))
        return "Unable to generate summary with the inference profile. The model response format was not recognized."
        
    except Exception as e:
        print(f"Error in generate_summary_with_bedrock: {str(e)}")
        return f"Error generating summary: {str(e)}"

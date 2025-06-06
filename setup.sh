#!/bin/bash

# Setup script for AI-Powered Document Summarization Application

# Set variables
STACK_NAME="ai-document-summarization-app"
BUCKET_NAME="ai-document-summarization-bucket-$(date +%s)"
TOPIC_NAME="ai-document-summary-notifications"
REGION="us-east-1"  # Change to your preferred region
MODEL_ID="anthropic.claude-3-7-sonnet-20250219-v1:0"  # Claude 3.7 Sonnet model ID
INFERENCE_PROFILE_NAME="US Anthropic Claude 3.7 Sonnet"
INFERENCE_PROFILE_ID="us.anthropic.claude-3-7-sonnet-20250219-v1:0"

# Print welcome message
echo "Setting up AI-Powered Document Summarization Application..."
echo "Stack Name: $STACK_NAME"
echo "S3 Bucket: $BUCKET_NAME"
echo "SNS Topic: $TOPIC_NAME"
echo "Region: $REGION"
echo "Bedrock Model: $MODEL_ID"

# Check if AWS CLI is installed
if ! command -v aws &> /dev/null; then
    echo "AWS CLI is not installed. Please install it first."
    exit 1
fi

# Check if SAM CLI is installed
if ! command -v sam &> /dev/null; then
    echo "AWS SAM CLI is not installed. Please install it first."
    exit 1
fi

# Check if Amazon Bedrock is enabled in the account
echo "Checking if Amazon Bedrock is enabled and Claude 3.7 Sonnet model is accessible..."
if ! aws bedrock list-foundation-models --query "modelSummaries[?modelId=='$MODEL_ID']" --output text --region $REGION &> /dev/null; then
    echo "Warning: Could not verify access to Claude 3.7 Sonnet model."
    echo "Please ensure that:"
    echo "1. Amazon Bedrock service is enabled in your AWS account"
    echo "2. You have requested access to the Claude 3.7 Sonnet model in the Bedrock console"
    echo "3. Your AWS credentials have permission to use Bedrock"
    
    read -p "Do you want to continue anyway? (y/n): " CONTINUE
    if [[ $CONTINUE != "y" && $CONTINUE != "Y" ]]; then
        echo "Setup aborted."
        exit 1
    fi
fi

# Create an inference profile for Claude 3.7 Sonnet
echo "Creating inference profile for Claude 3.7 Sonnet..."
INFERENCE_PROFILE_ARN=""
PROFILE_EXISTS=$(aws bedrock list-inference-profiles --query "inferenceProfileSummaries[?inferenceProfileId=='$INFERENCE_PROFILE_ID']" --output text --region $REGION)

if [ -z "$PROFILE_EXISTS" ]; then
    echo "Inference profile doesn't exists."
    echo "Setup aborted."
    exit 1
    
else
    echo "Inference profile $INFERENCE_PROFILE_NAME already exists"
    INFERENCE_PROFILE_ARN=$(aws bedrock list-inference-profiles --query "inferenceProfileSummaries[?inferenceProfileId=='$INFERENCE_PROFILE_ID'].inferenceProfileArn" --output text --region $REGION)
    echo "Using existing inference profile with ARN: $INFERENCE_PROFILE_ARN"
fi

# Create a deployment package
echo "Building the application..."
sam build -t template.yaml

# Step 1: Deploy the application without S3 event notifications
echo "Step 1: Deploying the application without S3 event notifications..."

# Deploy using the pre-created template.yaml (without S3 notifications)
echo "Deploying initial resources..."
sam deploy \
    --template-file template.yaml \
    --stack-name $STACK_NAME \
    --parameter-overrides BucketName=$BUCKET_NAME TopicName=$TOPIC_NAME ModelId=$MODEL_ID InferenceProfile=$INFERENCE_PROFILE_ARN \
    --capabilities CAPABILITY_IAM \
    --region $REGION \
    --resolve-s3

# Check if initial deployment was successful
if [ $? -ne 0 ]; then
    echo "Initial deployment failed. Please check the error messages above."
    exit 1
fi


# Check if deployment was successful
if [ $? -eq 0 ]; then
    echo "Deployment successful!"
    
    # Get outputs from CloudFormation stack
    BUCKET_NAME=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue" --output text --region $REGION)
    TOPIC_ARN=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query "Stacks[0].Outputs[?OutputKey=='TopicARN'].OutputValue" --output text --region $REGION)
    
    echo "AI-Powered Application is ready to use!"
    echo "Upload documents to S3 bucket: $BUCKET_NAME"
    echo "Subscribe to SNS topic to receive notifications: $TOPIC_ARN"
    
    # Create a sample subscription (optional)
    read -p "Would you like to subscribe an email to receive notifications? (y/n): " SUBSCRIBE
    if [[ $SUBSCRIBE == "y" || $SUBSCRIBE == "Y" ]]; then
        read -p "Enter your email address: " EMAIL
        aws sns subscribe \
            --topic-arn $TOPIC_ARN \
            --protocol email \
            --notification-endpoint $EMAIL \
            --region $REGION
        echo "Subscription request sent to $EMAIL. Please check your email to confirm the subscription."
    fi
    
    # Upload a sample document (optional)
    read -p "Would you like to upload a sample document to test the application? (y/n): " UPLOAD
    if [[ $UPLOAD == "y" || $UPLOAD == "Y" ]]; then
        # Create a sample document
        echo "Creating a sample document..."
        cat > sample_document.txt << EOL
# Sample Document for AI Summarization

## Introduction
This is a sample document to test the AI-powered document summarization application using DeepSeek-R1 on Amazon Bedrock.

## Key Points
1. The application uses serverless architecture on AWS
2. Documents are uploaded to an S3 bucket
3. A Lambda function processes the documents
4. DeepSeek-R1 on Amazon Bedrock generates intelligent summaries
5. Summaries are stored in DynamoDB
6. Notifications are sent via SNS

## Benefits
- Automated document processing
- High-quality AI-generated summaries
- Scalable serverless architecture
- Real-time notifications

## Conclusion
This sample demonstrates how AI can be used to extract meaningful insights from documents automatically.
EOL
        
        # Upload the sample document
        aws s3 cp sample_document.txt s3://$BUCKET_NAME/
        echo "Sample document uploaded to S3 bucket: $BUCKET_NAME"
        echo "Check your email for the summary notification (this may take a minute or two)."
    fi
else
    echo "Deployment failed. Please check the error messages above."
fi

#!/usr/bin/env bash

STACK_NAME="koenote-backend-stack"
PROFILE="syncbloom_yutabee_dev"
REGION="ap-northeast-1"

echo "======================================================"
echo "Building with SAM..."
echo "======================================================"
sam build \
  --template-file cloudformation/koenote_backend.yaml \
  --profile "$PROFILE" \
  --region "$REGION"

if [ $? -ne 0 ]; then
  echo "Error: sam build failed."
  exit 1
fi

echo "======================================================"
echo "Deploying stack: $STACK_NAME ..."
echo "======================================================"
sam deploy \
  --template-file .aws-sam/build/template.yaml \
  --stack-name "$STACK_NAME" \
  --capabilities CAPABILITY_NAMED_IAM \
  --resolve-s3 \
  --parameter-overrides \
    PublicSubnetAZ=ap-northeast-1a \
    PrivateSubnetAZ=ap-northeast-1c \
  --profile "$PROFILE" \
  --region "$REGION"

if [ $? -ne 0 ]; then
  echo "Error: sam deploy failed."
  exit 1
fi

#=====================================================
# 3) スタックのOutputsからPublicApiEndpointを取得
#=====================================================
ENDPOINT=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query "Stacks[0].Outputs[?OutputKey=='PublicApiEndpoint'].OutputValue" \
  --output text \
  --profile "$PROFILE" \
  --region "$REGION")

echo "------------------------------------------------------"
echo "Stack deployment complete."
echo "PublicApiEndpoint:"
echo "$ENDPOINT"
echo "------------------------------------------------------"

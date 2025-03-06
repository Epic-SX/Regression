

```bash
aws cloudformation create-stack \
  --stack-name koenote-backend-stack \
  --template-body file://cloudformation/koenote_backend.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameters \
    ParameterKey=PublicSubnetAZ,ParameterValue=ap-northeast-1a \
    ParameterKey=PrivateSubnetAZ,ParameterValue=ap-northeast-1c \
  --profile syncbloom_yutabee_dev
```

```bash
aws cloudformation describe-stack-events \
  --stack-name koenote-backend-stack \
  --profile syncbloom_yutabee_dev \
  --output json | jq -r '
    ["Timestamp", "ResourceType", "LogicalResourceId", "ResourceStatus", "ResourceStatusReason"],
    (.StackEvents[] | [.Timestamp, .ResourceType, .LogicalResourceId, .ResourceStatus, (.ResourceStatusReason // "N/A")])
    | @csv
  ' > stack-events.csv
```

```bash
aws cloudformation delete-stack \
  --stack-name koenote-backend-stack \
  --profile syncbloom_yutabee_dev
```
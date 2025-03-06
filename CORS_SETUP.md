# Fixing CORS Issues with S3 Uploads

This document explains how to fix CORS (Cross-Origin Resource Sharing) issues when uploading files to Amazon S3 from your web application.

## The Problem

You're encountering CORS errors when trying to upload audio chunks to your S3 bucket:

```
Access to fetch at 'https://regression-stack-regression-audio-ap-northeast-1.s3.amazonaws.com/...' from origin 'http://localhost:3000' has been blocked by CORS policy: Response to preflight request doesn't pass access control check: No 'Access-Control-Allow-Origin' header is present on the requested resource.
```

This happens because your web application (running on localhost:3000) is trying to make a cross-origin request to Amazon S3, but the S3 bucket doesn't have CORS configured to allow requests from your domain.

## Solution

### 1. Configure CORS on your S3 bucket

Use the provided `configure_s3_cors.py` script to configure CORS on your S3 bucket:

```bash
# Make sure you have AWS credentials configured
python configure_s3_cors.py --bucket regression-stack-regression-audio-ap-northeast-1 --origins http://localhost:3000 https://your-production-domain.com
```

This will configure your S3 bucket to accept cross-origin requests from the specified origins.

### 2. Update your frontend code

We've already updated the frontend code to include proper CORS headers in the fetch requests:

- Added `mode: 'cors'` to the fetch requests
- Added `credentials: 'same-origin'` to the API request

### 3. Verify AWS credentials

Make sure your AWS credentials have the necessary permissions to:
- Put objects in the S3 bucket
- Configure CORS on the S3 bucket

### 4. Alternative solution (if you can't configure S3 CORS)

If you don't have permissions to configure CORS on the S3 bucket, you can modify your Lambda function to proxy the upload:

1. Upload the audio chunks to your Lambda function
2. Have the Lambda function upload the chunks to S3
3. Return the S3 URLs to the frontend

This approach avoids direct browser-to-S3 communication, eliminating CORS issues.

## Testing

After implementing these changes:

1. Run your application locally
2. Try recording and uploading audio
3. Check the browser console for any CORS errors

If you still encounter issues, make sure the S3 bucket name is correct and that your AWS credentials have the necessary permissions. 
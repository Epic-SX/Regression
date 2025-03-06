import json
import os
import uuid
import boto3
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Attr
import openai
import tempfile
from typing import List, Dict
import subprocess
import wave
import datetime
import logging
import re

# CORS headers for all responses
CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',  # Or your specific domain
    'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token',
    'Access-Control-Allow-Methods': 'OPTIONS,GET,POST,PUT,DELETE'
}

TABLE_NAME = os.environ.get("TABLE_NAME", "KoenoteRecordings")
AUDIO_BUCKET_NAME = os.environ.get("AUDIO_BUCKET_NAME", "koenote-stack-koenote-audio-ap-northeast-1")

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
s3 = boto3.client("s3")

# Add OpenAI configuration
openai.api_key = os.environ.get("OPENAI_API_KEY")

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

def check_environment():
    """Check that all required environment variables are set"""
    required_vars = ['TABLE_NAME', 'AUDIO_BUCKET_NAME', 'OPENAI_API_KEY']
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        return False
    return True

def lambda_handler(event, context):
    """Lambda handler for API requests"""
    try:
        # Check environment variables
        if not check_environment():
            return {
                'statusCode': 500,
                'body': json.dumps({'error': 'Missing required environment variables'}),
                'headers': CORS_HEADERS
            }
        
        # Log the incoming event for debugging
        logger.info(f"Received event: {event}")
        
        # Check if this is a direct invocation from Step Functions
        if 'chunkKey' in event and 'sessionId' in event:
            return process_audio_chunk_for_step_function(event, context)
        
        # Check HTTP method and resource
        http_method = event.get('httpMethod')
        resource = event.get('resource', '')
        
        # Handle OPTIONS requests for CORS
        if http_method == 'OPTIONS':
            return {
                'statusCode': 200,
                'headers': CORS_HEADERS,
                'body': json.dumps({'message': 'CORS preflight request successful'})
            }
        
        # Handle DELETE request for a recording
        if http_method == 'DELETE' and event.get('path', '').startswith('/koenoto/'):
            try:
                # Extract the recording ID from the path
                recording_id = event.get('path', '').split('/')[-1]
                
                logger.info(f"Deleting recording with ID: {recording_id}")
                
                # Delete the recording from DynamoDB
                response = table.delete_item(
                    Key={'id': recording_id}
                )
                
                # Return success response
                return {
                    'statusCode': 200,
                    'body': json.dumps({'message': 'Recording deleted successfully'}),
                    'headers': CORS_HEADERS
                }
            except Exception as e:
                logger.error(f"Error deleting recording: {e}")
                import traceback
                logger.error(traceback.format_exc())
                return {
                    'statusCode': 500,
                    'body': json.dumps({'error': str(e)}),
                    'headers': CORS_HEADERS
                }
        
        # Handle save-recording endpoint
        if http_method == 'POST' and resource == '/koenoto/save-recording':
            try:
                # Parse the request body
                body = json.loads(event.get('body', '{}')) if isinstance(event.get('body'), str) else event.get('body', {})
                recording = body.get('recording', {})
                
                logger.info(f"Saving recording: {recording}")
                
                # Validate required fields
                required_fields = ['id', 'title', 'user_id']
                for field in required_fields:
                    if field not in recording:
                        return {
                            'statusCode': 400,
                            'body': json.dumps({'error': f'Missing required field: {field}'}),
                            'headers': CORS_HEADERS
                        }
                
                # Save the recording to DynamoDB
                table.put_item(Item=recording)
                
                return {
                    'statusCode': 200,
                    'body': json.dumps({'message': 'Recording saved successfully', 'id': recording['id']}),
                    'headers': CORS_HEADERS
                }
            except Exception as e:
                logger.error(f"Error saving recording: {e}")
                import traceback
                logger.error(traceback.format_exc())
                return {
                    'statusCode': 500,
                    'body': json.dumps({'error': str(e)}),
                    'headers': CORS_HEADERS
                }
        
        # Handle POST requests for creating recordings or generating presigned URLs
        if http_method == 'POST':
            # Check if this is a request for a presigned URL
            resource = event.get('resource', '')
            
            if resource == '/koenoto/presigned-url':
                # Parse the request body
                body = json.loads(event.get('body', '{}'))
                filename = body.get('filename')
                content_type = body.get('contentType', 'audio/webm')
                
                if not filename:
                    return {
                        'statusCode': 400,
                        'body': json.dumps({'error': 'Filename is required'}),
                        'headers': CORS_HEADERS
                    }
                
                # Generate a presigned URL for uploading
                try:
                    # Create a custom client with specific config for presigned URLs
                    s3_client = boto3.client('s3', config=boto3.session.Config(
                        signature_version='s3v4',
                        s3={'addressing_style': 'virtual'}
                    ))
                    
                    presigned_url = s3_client.generate_presigned_url(
                        'put_object',
                        Params={
                            'Bucket': AUDIO_BUCKET_NAME,
                            'Key': filename,
                            'ContentType': content_type,
                        },
                        ExpiresIn=300,  # URL expires in 5 minutes
                    )
                    
                    return {
                        'statusCode': 200,
                        'body': json.dumps({
                            'presignedUrl': presigned_url,
                            'key': filename,
                            'uploadUrl': presigned_url  # For backward compatibility
                        }),
                        'headers': CORS_HEADERS
                    }
                except Exception as e:
                    logger.error(f"Error generating presigned URL: {e}")
                    return {
                        'statusCode': 500,
                        'body': json.dumps({'error': str(e)}),
                        'headers': CORS_HEADERS
                    }
            
            # If not a presigned URL request, handle as a recording creation
            if resource == '/koenoto/process-audio':
                try:
                    body = json.loads(event.get('body', '{}'))
                    audio_keys = body.get('audioKeys', [])
                    user_id = body.get('userId', 'default')
                    complete_audio_url = body.get('completeAudioUrl')
                    
                    if not audio_keys:
                        return {
                            'statusCode': 400,
                            'body': json.dumps({'error': 'No audio keys provided'}),
                            'headers': CORS_HEADERS
                        }
                    
                    # Start the Step Functions execution
                    step_functions_client = boto3.client('stepfunctions')
                    execution_input = {
                        'audioKeys': audio_keys,
                        'audioBucket': AUDIO_BUCKET_NAME,
                        'userId': user_id,
                        'completeAudioUrl': complete_audio_url
                    }
                    
                    # Get the Step Function ARN from environment variable
                    step_function_arn = os.environ.get('STEP_FUNCTION_ARN')
                    
                    if not step_function_arn:
                        logger.warning("STEP_FUNCTION_ARN not set, falling back to direct processing")
                        # Fallback to direct processing
                        results = []
                        for key in audio_keys:
                            result = process_single_chunk(key, AUDIO_BUCKET_NAME)
                            results.append(result)
                        
                        # Combine results
                        final_result = combine_transcription_results(results, complete_audio_url, user_id, save_to_db=False)
                        
                        return {
                            'statusCode': 200,
                            'body': json.dumps(final_result),
                            'headers': CORS_HEADERS
                        }
                    
                    # Start Step Functions execution
                    logger.info(f"Starting Step Functions execution with ARN: {step_function_arn}")
                    response = step_functions_client.start_execution(
                        stateMachineArn=step_function_arn,
                        input=json.dumps(execution_input)
                    )
                    
                    return {
                        'statusCode': 202,
                        'body': json.dumps({
                            'message': 'Audio processing started',
                            'executionArn': response['executionArn']
                        }),
                        'headers': CORS_HEADERS
                    }
                except Exception as e:
                    logger.error(f"Error starting audio processing: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    return {
                        'statusCode': 500,
                        'body': json.dumps({'error': str(e)}),
                        'headers': CORS_HEADERS
                    }
            
            # If not a process-audio request, handle as a recording creation
            if resource == '/koenoto/process-chunk':
                try:
                    body = json.loads(event.get('body', '{}')) if isinstance(event.get('body'), str) else event.get('body', {})
                    chunk_key = body.get('chunkKey')
                    bucket = body.get('bucket', AUDIO_BUCKET_NAME)
                    
                    if not chunk_key:
                        return {
                            'statusCode': 400,
                            'body': json.dumps({'error': 'No chunk key provided'}),
                            'headers': CORS_HEADERS
                        }
                    
                    # Process the chunk
                    result = process_single_chunk(chunk_key, bucket)
                    
                    return {
                        'statusCode': 200,
                        'body': json.dumps(result),
                        'headers': CORS_HEADERS
                    }
                except Exception as e:
                    logger.error(f"Error processing chunk: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    return {
                        'statusCode': 500,
                        'body': json.dumps({'error': str(e)}),
                        'headers': CORS_HEADERS
                    }
            
            # If not a process-audio request, handle as a recording creation
            elif resource == '/koenoto/combine-results':
                try:
                    body = json.loads(event.get('body', '{}')) if isinstance(event.get('body'), str) else event.get('body', {})
                    transcription_results = body.get('transcriptionResults', [])
                    complete_audio_url = body.get('completeAudioUrl')
                    user_id = body.get('userId', 'default')
                    session_id = body.get('sessionId')
                    save_to_db = body.get('saveToDb', False)  # Default to False
                    
                    logger.info(f"Combining results for session {session_id}, user {user_id}, save_to_db: {save_to_db}")
                    
                    result = combine_transcription_results(
                        transcription_results, 
                        complete_audio_url, 
                        user_id, 
                        session_id,
                        save_to_db=save_to_db
                    )
                    
                    return {
                        'statusCode': 200,
                        'body': json.dumps(result),
                        'headers': CORS_HEADERS
                    }
                except Exception as e:
                    logger.error(f"Error combining results: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    return {
                        'statusCode': 500,
                        'body': json.dumps({'error': str(e)}),
                        'headers': CORS_HEADERS
                    }
            
            # If not a process-audio request, handle as a recording creation
            elif resource == '/koenoto/test-step-function':
                try:
                    body = json.loads(event.get('body', '{}'))
                    test_payload = body.get('payload', {})
                    
                    # Process a test chunk directly
                    result = process_audio_chunk_for_step_function(test_payload, context)
                    
                    return {
                        'statusCode': 200,
                        'body': json.dumps(result),
                        'headers': CORS_HEADERS
                    }
                except Exception as e:
                    logger.error(f"Error testing step function: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    return {
                        'statusCode': 500,
                        'body': json.dumps({'error': str(e)}),
                        'headers': CORS_HEADERS
                    }
            
            # If not a process-audio request, handle as a recording creation
            elif resource == '/koenoto/debug-execution':
                try:
                    # Get the execution ARN from query parameters
                    query_params = event.get('queryStringParameters', {}) or {}
                    execution_arn = query_params.get('executionArn')
                    
                    if not execution_arn:
                        return {
                            'statusCode': 400,
                            'body': json.dumps({'error': 'executionArn is required'}),
                            'headers': CORS_HEADERS
                        }
                    
                    debug_info = debug_step_functions_execution(execution_arn)
                    
                    return {
                        'statusCode': 200,
                        'body': json.dumps(debug_info),
                        'headers': CORS_HEADERS
                    }
                except Exception as e:
                    logger.error(f"Error debugging execution: {e}")
                    return {
                        'statusCode': 500,
                        'body': json.dumps({'error': str(e)}),
                        'headers': CORS_HEADERS
                    }
            
            # If not a process-audio request, handle as a recording creation
            elif resource == '/koenoto/process-status':
                if http_method == 'GET':
                    try:
                        execution_arn = query_parameters.get('executionArn')
                        if not execution_arn:
                            return {
                                'statusCode': 400,
                                'body': json.dumps({'error': 'executionArn is required'}),
                                'headers': CORS_HEADERS
                            }
                        
                        # Get the execution status from Step Functions
                        step_functions_client = boto3.client('stepfunctions')
                        execution = step_functions_client.describe_execution(
                            executionArn=execution_arn
                        )
                        
                        status = execution['status']
                        logger.info(f"Execution status for {execution_arn}: {status}")
                        
                        if status == 'SUCCEEDED':
                            output = execution.get('output')
                            try:
                                # 出力を解析
                                result = json.loads(output) if output else {}
                                return {
                                    'statusCode': 200,
                                    'body': json.dumps({
                                        'status': 'completed',
                                        'result': result
                                    }),
                                    'headers': CORS_HEADERS
                                }
                            except Exception as e:
                                logger.error(f"実行出力の解析エラー: {e}")
                                return {
                                    'statusCode': 200,
                                    'body': json.dumps({
                                        'status': 'completed',
                                        'error': '実行結果の解析に失敗しました'
                                    }, ensure_ascii=False),
                                    'headers': CORS_HEADERS
                                }
                        elif status == 'FAILED':
                            # 実行失敗
                            return {
                                'statusCode': 200,
                                'body': json.dumps({
                                    'status': 'failed',
                                    'error': 'ステップファンクションの実行に失敗しました'
                                }, ensure_ascii=False),
                                'headers': CORS_HEADERS
                            }
                        else:
                            # まだ実行中
                            return {
                                'statusCode': 200,
                                'body': json.dumps({
                                    'status': 'processing',
                                    'message': f'実行中です'
                                }, ensure_ascii=False),
                                'headers': CORS_HEADERS
                            }
                            
                    except Exception as e:
                        logger.error(f"Error checking process status: {e}")
                        import traceback
                        logger.error(traceback.format_exc())
                        return {
                            'statusCode': 500,
                            'body': json.dumps({'error': str(e)}),
                            'headers': CORS_HEADERS
                        }
            
            # If not a process-audio request, handle as a recording creation
            try:
                body = json.loads(event.get('body', '{}'))
                
                # Create a new recording
                recording_id = str(uuid.uuid4())
                timestamp = datetime.datetime.now().isoformat()
                
                item = {
                    'id': recording_id,
                    **body,
                    'timestamp': timestamp
                }
                
                table.put_item(Item=item)
                
                return {
                    'statusCode': 201,
                    'body': json.dumps({
                        'message': 'Recording created successfully',
                        'item': item
                    }),
                    'headers': CORS_HEADERS
                }
            except Exception as e:
                logger.error(f"Error creating recording: {e}")
                return {
                    'statusCode': 500,
                    'body': json.dumps({'error': str(e)}),
                    'headers': CORS_HEADERS
                }
        
        # Handle GET requests for listing recordings
        if http_method == 'GET':
            resource = event.get('resource', '')
            
            # Check if this is a request for a specific recording or a list
            path_parameters = event.get('pathParameters', {}) or {}
            query_parameters = event.get('queryStringParameters', {}) or {}
            
            # Check if this is a request for a pre-signed URL
            if path_parameters and path_parameters.get('proxy') == 'get-upload-url':
                # Get the key from query parameters
                key = query_parameters.get('key') if query_parameters else None
                if not key:
                    return {
                        'statusCode': 400,
                        'body': json.dumps({'error': 'No key provided'}),
                        'headers': CORS_HEADERS
                    }
                return generate_presigned_url(key)
            
            # Check if this is a request for intermediate results
            if path_parameters and path_parameters.get('proxy') == 'intermediate-results':
                return get_intermediate_results(event, context)
            
            # Check if this is a request for process-status
            if resource == '/koenoto/process-status':
                if http_method == 'GET':
                    try:
                        execution_arn = query_parameters.get('executionArn')
                        if not execution_arn:
                            return {
                                'statusCode': 400,
                                'body': json.dumps({'error': 'executionArn is required'}),
                                'headers': CORS_HEADERS
                            }
                        
                        # Get the execution status from Step Functions
                        step_functions_client = boto3.client('stepfunctions')
                        execution = step_functions_client.describe_execution(
                            executionArn=execution_arn
                        )
                        
                        status = execution['status']
                        logger.info(f"Execution status for {execution_arn}: {status}")
                        
                        if status == 'SUCCEEDED':
                            output = execution.get('output')
                            try:
                                # 出力を解析
                                result = json.loads(output) if output else {}
                                return {
                                    'statusCode': 200,
                                    'body': json.dumps({
                                        'status': 'completed',
                                        'result': result
                                    }),
                                    'headers': CORS_HEADERS
                                }
                            except Exception as e:
                                logger.error(f"実行出力の解析エラー: {e}")
                                return {
                                    'statusCode': 200,
                                    'body': json.dumps({
                                        'status': 'completed',
                                        'error': '実行結果の解析に失敗しました'
                                    }, ensure_ascii=False),
                                    'headers': CORS_HEADERS
                                }
                        elif status == 'FAILED':
                            # 実行失敗
                            return {
                                'statusCode': 200,
                                'body': json.dumps({
                                    'status': 'failed',
                                    'error': 'ステップファンクションの実行に失敗しました'
                                }, ensure_ascii=False),
                                'headers': CORS_HEADERS
                            }
                        else:
                            # まだ実行中
                            return {
                                'statusCode': 200,
                                'body': json.dumps({
                                    'status': 'processing',
                                    'message': f'実行中です'
                                }, ensure_ascii=False),
                                'headers': CORS_HEADERS
                            }
                            
                    except Exception as e:
                        logger.error(f"Error checking process status: {e}")
                        import traceback
                        logger.error(traceback.format_exc())
                        return {
                            'statusCode': 500,
                            'body': json.dumps({'error': str(e)}),
                            'headers': CORS_HEADERS
                        }
            
            # Fix: Add null check for query_parameters
            user_id = query_parameters.get('user_id') if query_parameters else 'default'
            
            # If we have a recording ID in the path, get that specific recording
            if path_parameters and path_parameters.get('id'):
                recording_id = path_parameters.get('id')
                return get_recording(recording_id)
            else:
                # Otherwise, list all recordings for the user
                return list_recordings(user_id)
        
        # Rest of your handler code...
    except Exception as e:
        logger.error(f"Error in lambda_handler: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e)
            }),
            'headers': CORS_HEADERS
        }

def process_single_audio_chunk(chunk_key, bucket, session_id=None, chunk_index=0):
    """Process a single audio chunk with session tracking"""
    local_path = None
    try:
        logger.info(f"Processing audio chunk {chunk_key} (session: {session_id}, index: {chunk_index})")
        
        # Create a proper file extension
        file_ext = os.path.splitext(chunk_key)[1]
        if not file_ext:
            file_ext = '.webm'  # Default extension if none is found
            
        # Download the audio file from S3
        local_path = f"/tmp/{uuid.uuid4()}{file_ext}"
        
        try:
            s3.download_file(bucket, chunk_key, local_path)
            logger.info(f"Downloaded {chunk_key} to {local_path}")
        except Exception as e:
            logger.error(f"Error downloading {chunk_key}: {e}")
            return {
                "chunk": chunk_key,
                "text": "[Download failed]",
                "error": str(e),
                "session_id": session_id,
                "chunk_index": chunk_index
            }
        
        # Validate the audio file
        if not is_valid_audio(local_path):
            logger.warning(f"Invalid audio file detected for {chunk_key}, attempting repair")
            repaired_path = repair_audio(local_path)
            if repaired_path:
                local_path = repaired_path
                logger.info(f"Successfully repaired audio file for {chunk_key}")
            else:
                logger.error(f"Could not repair audio file for {chunk_key}")
                return {
                    "chunk": chunk_key,
                    "text": "[Invalid audio file]",
                    "session_id": session_id,
                    "chunk_index": chunk_index
                }
        
        # Get duration with fallback
        try:
            duration = get_audio_duration(local_path)
        except Exception as e:
            logger.warning(f"Error getting duration, using default: {e}")
            duration = 30.0  # Default assumption
        
        # Transcribe the audio
        try:
            logger.info(f"Attempting to transcribe {chunk_key} with Whisper API")
            
            # Convert audio to a format Whisper can handle better if needed
            converted_path = convert_to_mp3_if_needed(local_path)
            use_path = converted_path if converted_path else local_path
            
            # Log file details before sending to Whisper
            file_size = os.path.getsize(use_path)
            logger.info(f"Sending file to Whisper API: {use_path}, size: {file_size} bytes")
            
            with open(use_path, 'rb') as audio_file:
                transcription_response = openai.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language="ja",
                    response_format="verbose_json",  # Get more detailed response
                    prompt="これは会議や会話の録音です。話者ごとに文を区切り、句読点を適切に入れてください。「はい」「えーと」などの新しい発言の始まりには改行を入れてください。"
                )
            
            # Log the full response structure for debugging
            logger.info(f"Whisper API response structure: {json.dumps(transcription_response.model_dump(), ensure_ascii=False)}")
            
            # Extract the text from the response
            if hasattr(transcription_response, 'text'):
                transcription_text = transcription_response.text
            else:
                # Fallback if structure is different
                transcription_text = str(transcription_response)
            
            logger.info(f"Raw transcription: {transcription_text[:200]}...")
            
            # Clean up any repeated phrases and format the text
            cleaned_text = clean_repeated_phrases(transcription_text)
            formatted_text = format_transcription(cleaned_text)
            
            logger.info(f"Transcription successful for {chunk_key}")
            
            # Clean up temporary files
            if converted_path and converted_path != local_path:
                os.remove(converted_path)
            
            return {
                "chunk": chunk_key,
                "text": formatted_text,
                "structured_sentences": structure_transcription(formatted_text),
                "duration": duration,
                "session_id": session_id,
                "chunk_index": chunk_index
            }
            
        except Exception as e:
            logger.error(f"Error transcribing {chunk_key}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "chunk": chunk_key,
                "text": f"[Transcription failed: {str(e)}]",
                "error": str(e),
                "session_id": session_id,
                "chunk_index": chunk_index
            }
    finally:
        # Clean up the local file
        if local_path and os.path.exists(local_path):
            try:
                os.remove(local_path)
                logger.info(f"Cleaned up temporary file: {local_path}")
            except Exception as e:
                logger.warning(f"Failed to clean up temporary file {local_path}: {e}")

def convert_to_mp3_if_needed(file_path):
    """Convert audio to MP3 format if it's not already in a format Whisper handles well"""
    file_ext = os.path.splitext(file_path)[1].lower()
    
    # If already MP3 or WAV, no need to convert
    if file_ext in ['.mp3', '.wav']:
        return None
    
    try:
        output_path = f"/tmp/{uuid.uuid4()}.mp3"
        
        # Use ffmpeg to convert to MP3
        cmd = [
            'ffmpeg', '-i', file_path, 
            '-ar', '16000',  # 16kHz sample rate
            '-ac', '1',      # Mono
            '-c:a', 'libmp3lame',
            '-q:a', '4',     # Quality setting
            output_path
        ]
        
        logger.info(f"Converting audio: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error(f"Conversion failed: {result.stderr}")
            return None
            
        logger.info(f"Successfully converted {file_path} to {output_path}")
        return output_path
    except Exception as e:
        logger.error(f"Error converting audio: {e}")
        return None

def store_chunk_result(session_id, chunk_index, result):
    """Store a chunk result in S3 temporarily"""
    try:
        # Create a key for the temporary result
        temp_key = f"temp_results/{session_id}/{chunk_index}.json"
        
        # Store the result in S3
        s3.put_object(
            Bucket=AUDIO_BUCKET_NAME,
            Key=temp_key,
            Body=json.dumps(result),
            ContentType='application/json'
        )
        
        logger.info(f"Stored temporary result for session {session_id}, chunk {chunk_index}")
        return True
    except Exception as e:
        logger.error(f"Error storing temporary result: {e}")
        return False

def combine_session_results(session_id, user_id="default"):
    """Combine all results for a session and generate a summary"""
    try:
        # List all temporary results for this session
        prefix = f"temp_results/{session_id}/"
        response = s3.list_objects_v2(
            Bucket=AUDIO_BUCKET_NAME,
            Prefix=prefix
        )
        
        if 'Contents' not in response:
            logger.error(f"No results found for session {session_id}")
            return {
                "error": "No results found for this session"
            }
        
        # Get all result files
        result_files = [item['Key'] for item in response['Contents']]
        logger.info(f"Found {len(result_files)} result files for session {session_id}")
        
        # Sort by chunk index
        result_files.sort(key=lambda x: int(x.split('/')[-1].split('.')[0]))
        
        # Combine all results
        all_results = []
        all_text = ""
        
        for file_key in result_files:
            try:
                # Get the result file
                response = s3.get_object(
                    Bucket=AUDIO_BUCKET_NAME,
                    Key=file_key
                )
                
                # Parse the result
                result = json.loads(response['Body'].read().decode('utf-8'))
                all_results.append(result)
                
                # Add the text to the combined text
                if 'text' in result and result['text'] and not result['text'].startswith('['):
                    all_text += " " + result['text']
            except Exception as e:
                logger.error(f"Error processing result file {file_key}: {e}")
        
        # Generate summary from the combined text
        summary = {}
        if all_text.strip():
            try:
                logger.info(f"Generating summary for session {session_id}")
                summary = generate_summary_in_chunks(all_text)
            except Exception as e:
                logger.error(f"Error generating summary: {e}")
                summary = {
                    "title": f"録音_{session_id[:8]}",
                    "summary": all_text[:200] + "..." if len(all_text) > 200 else all_text,
                    "keywords": []
                }
        
        # Create the final result
        final_result = {
            "sessionId": session_id,
            "userId": user_id,
            "timestamp": datetime.datetime.now().isoformat(),
            "chunks": all_results,
            "combinedText": all_text,
            "summary": summary
        }
        
        # Store the final result
        final_key = f"final_results/{user_id}/{session_id}.json"
        s3.put_object(
            Bucket=AUDIO_BUCKET_NAME,
            Key=final_key,
            Body=json.dumps(final_result),
            ContentType='application/json'
        )
        
        # Save to DynamoDB for persistence
        save_to_dynamodb(final_result)
        
        # Clean up temporary files
        cleanup_temp_files(session_id)
        
        return final_result
    
    except Exception as e:
        logger.error(f"Error combining session results: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "error": f"Error combining results: {str(e)}"
        }

def save_to_dynamodb(final_result):
    """Save the final result to DynamoDB"""
    try:
        session_id = final_result.get("sessionId")
        user_id = final_result.get("userId", "default")
        combined_text = final_result.get("combinedText", "")
        summary = final_result.get("summary", {})
        
        # Create a DynamoDB item
        item = {
            "id": session_id,
            "user_id": user_id,
            "title": summary.get("title", f"録音_{session_id[:8]}"),
            "date": datetime.datetime.now().strftime("%Y-%m-%d"),
            "start_time": datetime.datetime.now().strftime("%H:%M:%S"),
            "duration": "00:00",  # Calculate actual duration if needed
            "transcript": combined_text,
            "summary": summary.get("summary", "要約なし"),
            "keywords": summary.get("keywords", []),
            "processingStatus": "COMPLETED",
            "timestamp": datetime.datetime.now().isoformat()
        }
        
        # Save to DynamoDB
        table.put_item(Item=item)
        logger.info(f"Saved final result to DynamoDB for session {session_id}")
        return True
    
    except Exception as e:
        logger.error(f"Error saving to DynamoDB: {e}")
        return False

def cleanup_temp_files(session_id):
    """Clean up temporary files for a session"""
    try:
        # List all temporary files
        prefix = f"temp_results/{session_id}/"
        response = s3.list_objects_v2(
            Bucket=AUDIO_BUCKET_NAME,
            Prefix=prefix
        )
        
        if 'Contents' not in response:
            return
        
        # Delete all temporary files
        objects_to_delete = [{'Key': item['Key']} for item in response['Contents']]
        
        if objects_to_delete:
            s3.delete_objects(
                Bucket=AUDIO_BUCKET_NAME,
                Delete={
                    'Objects': objects_to_delete
                }
            )
            
        logger.info(f"Cleaned up {len(objects_to_delete)} temporary files for session {session_id}")
    except Exception as e:
        logger.error(f"Error cleaning up temporary files: {e}")

def process_single_chunk(key, bucket):
    """Process a single audio chunk to get transcription"""
    try:
        logger.info(f"Processing audio chunk: {key} from bucket: {bucket}")
        
        # Download the audio file from S3
        with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as temp_file:
            s3.download_file(bucket, key, temp_file.name)
            temp_path = temp_file.name
        
        # Transcribe the audio using OpenAI Whisper API
        with open(temp_path, 'rb') as audio_file:
            transcript_response = openai.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ja"
            )
        
        # Clean up the temporary file
        os.unlink(temp_path)
        
        # Return the transcription result
        return {
            'key': key,
            'transcript': transcript_response.text
        }
    except Exception as e:
        logger.error(f"Error processing audio chunk {key}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            'key': key,
            'transcript': f"Error transcribing audio: {str(e)}"
        }

def combine_transcription_results(results, audio_url, user_id, session_id=None, save_to_db=True):
    """Combine transcription results and generate summary"""
    try:
        # Log the input for debugging
        logger.info(f"Combining results: {json.dumps(results)}")
        
        # Extract text from results, handling different possible structures
        all_text = ""
        for result in results:
            # Handle nested result structure
            if isinstance(result, dict):
                if 'text' in result:
                    all_text += " " + result['text']
                elif 'result' in result and isinstance(result['result'], dict) and 'text' in result['result']:
                    all_text += " " + result['result']['text']
                elif 'transcript' in result:
                    all_text += " " + result['transcript']
        
        all_text = all_text.strip()
        
        if not all_text:
            logger.warning("No transcript content found in results")
            all_text = "[No transcript content]"
        
        # Format the transcription text
        formatted_text = format_transcription(all_text)
        
        # Generate summary using OpenAI
        summary_data = generate_summary_from_text(formatted_text)
        
        # Create a recording entry
        recording_id = session_id or str(uuid.uuid4())
        
        # Get current date and time
        now = datetime.datetime.now()
        date = now.strftime("%Y-%m-%d")
        start_time = now.strftime("%H:%M:%S")
        timestamp = now.isoformat()
        
        # Calculate total duration if available
        total_duration = 0
        for result in results:
            if isinstance(result, dict) and 'duration' in result:
                total_duration += result['duration']
            elif isinstance(result, dict) and 'result' in result and isinstance(result['result'], dict) and 'duration' in result['result']:
                total_duration += result['result']['duration']
        
        duration_str = format_duration(total_duration) if total_duration > 0 else '00:00:30'
        
        # Create the recording item
        item = {
            'id': recording_id,
            'title': summary_data.get('title', '会議概要'),
            'date': date,
            'start_time': start_time,
            'duration': duration_str,
            'transcript': formatted_text,  # Use the formatted text
            'summary': summary_data.get('summary', 'トランスクリプトコンテンツは提供されません。'),
            'keywords': summary_data.get('keywords', []),
            'user_id': user_id,
            'timestamp': timestamp
        }
        
        # Add audioUrl if provided
        if audio_url:
            item['audioUrl'] = audio_url
        
        # If we have audio chunks, store them as well
        audio_chunks = []
        for result in results:
            if isinstance(result, dict) and 'chunk' in result:
                audio_chunks.append(result['chunk'])
        
        if audio_chunks:
            item['audioChunks'] = audio_chunks
            logger.info(f"Added {len(audio_chunks)} audio chunks to item")
        
        # Save to DynamoDB only if save_to_db is True
        if save_to_db:
            table.put_item(Item=item)
            logger.info(f"Saved recording {recording_id} to DynamoDB")
        else:
            logger.info(f"Generated recording {recording_id} but not saving to DynamoDB")
        
        return item
    except Exception as e:
        logger.error(f"Error combining transcription results: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            'error': f"Error processing audio: {str(e)}"
        }

def format_duration(seconds):
    """Format duration in seconds to HH:MM:SS"""
    hours, remainder = divmod(int(seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

def calculate_duration_from_chunks(chunk_keys: List[str]) -> str:
    """
    音声チャンクから総録音時間を計算する
    """
    try:
        total_duration = 0
        
        for key in chunk_keys:
            try:
                # S3からチャンクをダウンロード
                with tempfile.NamedTemporaryFile(suffix=os.path.splitext(key)[1], delete=False) as temp_file:
                    s3.download_file(AUDIO_BUCKET_NAME, key, temp_file.name)
                    
                    # FFprobeで音声の長さを取得
                    try:
                        result = subprocess.run([
                            'ffprobe', 
                            '-v', 'error', 
                            '-show_entries', 'format=duration', 
                            '-of', 'default=noprint_wrappers=1:nokey=1', 
                            temp_file.name
                        ], capture_output=True, text=True, check=True)
                        
                        duration = float(result.stdout.strip())
                        total_duration += duration
                    except Exception as e:
                        print(f"Error getting duration for chunk {key}: {str(e)}")
                    
                    # 一時ファイルを削除
                    os.unlink(temp_file.name)
            except Exception as e:
                print(f"Error processing chunk {key} for duration: {str(e)}")
        
        # 時間:分:秒の形式に変換
        hours = int(total_duration // 3600)
        minutes = int((total_duration % 3600) // 60)
        seconds = int(total_duration % 60)
        
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    except Exception as e:
        print(f"Error calculating duration: {str(e)}")
        return "00:00:00"

def get_intermediate_results(event, context):
    """
    中間処理結果を取得するエンドポイント
    """
    try:
        # クエリパラメータからキーを取得
        query_params = event.get('queryStringParameters', {}) or {}
        key = query_params.get('key')
        
        if not key:
            return {
                'statusCode': 400,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'Missing required parameter: key'})
            }
        
        # S3から中間結果を取得
        try:
            response = s3.get_object(Bucket=AUDIO_BUCKET_NAME, Key=key)
            results = json.loads(response['Body'].read().decode('utf-8'))
            
            return {
                'statusCode': 200,
                'headers': CORS_HEADERS,
                'body': json.dumps(results)
            }
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                return {
                    'statusCode': 404,
                    'headers': CORS_HEADERS,
                    'body': json.dumps({'error': f'Intermediate results not found: {key}'})
                }
            else:
                raise
        
    except Exception as e:
        print(f"Error getting intermediate results: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({'error': str(e)})
        }

def generate_presigned_url(key):
    """Generate a pre-signed URL for uploading a file to S3"""
    try:
        # Create a custom client with specific config for presigned URLs
        s3_client = boto3.client('s3', config=boto3.session.Config(
            signature_version='s3v4',
            s3={'addressing_style': 'virtual'}
        ))
        
        # Generate a pre-signed URL for uploading
        presigned_url = s3_client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': AUDIO_BUCKET_NAME,
                'Key': key,
                'ContentType': 'audio/webm',
            },
            ExpiresIn=300,  # URL expires in 5 minutes
        )
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'uploadUrl': presigned_url,
                'key': key
            }),
            'headers': CORS_HEADERS
        }
    except Exception as e:
        logger.error(f"Error generating pre-signed URL: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e)
            }),
            'headers': CORS_HEADERS
        }

def is_valid_audio(file_path):
    """Improved audio validation function"""
    try:
        # Use a more reliable method to check audio validity
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-i', file_path],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True
        )
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Error validating audio file: {e}")
        return False

def repair_audio(file_path):
    """Attempt to repair a corrupted audio file using ffmpeg"""
    try:
        output_path = f"{file_path}.repaired{os.path.splitext(file_path)[1]}"
        
        # Try to repair by re-encoding
        result = subprocess.run([
            'ffmpeg',
            '-v', 'error',
            '-i', file_path,
            '-c:a', 'copy',
            output_path
        ], stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        
        if result.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            logger.info(f"Successfully repaired audio file: {file_path}")
            return output_path
        else:
            logger.error(f"Failed to repair audio file: {file_path}")
            return None
    except Exception as e:
        logger.error(f"Error repairing audio file: {e}")
        return None

def get_audio_duration(file_path):
    """Get the duration of an audio file using ffprobe"""
    try:
        result = subprocess.run([
            'ffprobe', 
            '-v', 'error', 
            '-show_entries', 'format=duration', 
            '-of', 'default=noprint_wrappers=1:nokey=1', 
            file_path
        ], capture_output=True, text=True, check=True)
        
        duration = float(result.stdout.strip())
        return duration
    except Exception as e:
        logger.error(f"Error getting audio duration: {e}")
        return 30.0  # Default duration

def detect_repetitions(text, min_length=5, threshold=3):
    """Improved repetition detection with better parameters and filtering"""
    if not text or len(text) < min_length * threshold:
        return []
    
    # Break text into smaller chunks to avoid excessive matching
    chunk_size = 1000
    text_chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
    
    all_repetitions = []
    for chunk in text_chunks:
        # Find all phrases of length min_length or greater that repeat
        phrases = {}
        for i in range(len(chunk) - min_length + 1):
            phrase = chunk[i:i+min_length]
            if phrase in phrases:
                phrases[phrase] += 1
            else:
                phrases[phrase] = 1
        
        # Filter to significant repetitions
        repetitions = [(phrase, count) for phrase, count in phrases.items() 
                      if count >= threshold and not phrase.isspace()]
        all_repetitions.extend(repetitions)
    
    # Sort by count (most frequent first)
    all_repetitions.sort(key=lambda x: x[1], reverse=True)
    
    # Only report top 5 most significant repetitions to avoid noise
    return all_repetitions[:5]

def process_audio_chunk_for_step_function(event, context):
    """Process a single audio chunk as part of a Step Functions workflow"""
    try:
        # Log the entire event for debugging
        logger.info(f"Received event in process_audio_chunk_for_step_function: {json.dumps(event)}")
        
        # Extract parameters from the event
        chunk_key = event.get('chunkKey')
        bucket = event.get('bucket', AUDIO_BUCKET_NAME)
        session_id = event.get('sessionId', str(uuid.uuid4()))
        chunk_index = event.get('chunkIndex', 0)
        
        logger.info(f"Processing chunk: {chunk_key}, bucket: {bucket}, session: {session_id}, index: {chunk_index}")
        
        if not chunk_key:
            logger.error("No chunk key provided in the event")
            return {
                'statusCode': 400,
                'error': 'No chunk key provided'
            }
        
        # Process the chunk
        result = process_single_audio_chunk(chunk_key, bucket, session_id, chunk_index)
        logger.info(f"Processed chunk result: {json.dumps(result)}")
        
        # Store the result for debugging/recovery
        try:
            store_chunk_result(session_id, chunk_index, result)
        except Exception as store_error:
            logger.warning(f"Failed to store chunk result: {store_error}")
        
        return {
            'statusCode': 200,
            'result': result,
            'sessionId': session_id,
            'chunkIndex': chunk_index
        }
    except Exception as e:
        logger.error(f"Error in process_audio_chunk_for_step_function: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            'statusCode': 500,
            'error': str(e),
            'sessionId': event.get('sessionId', 'unknown'),
            'chunkIndex': event.get('chunkIndex', -1)
        }

def transcribe_with_whisper(audio_file_path):
    """Transcribe audio using OpenAI's Whisper API"""
    try:
        with open(audio_file_path, 'rb') as audio_file:
            transcription = openai.audio.transcriptions.create(
                file=audio_file,
                model="whisper-1",
                language="ja",
                response_format="text",
                temperature=0.3,
                prompt="これは会議や会話の録音です。話者ごとに文を区切り、句読点を適切に入れてください。「はい」「えーと」などの新しい発言の始まりには改行を入れてください。"
            )
        
        # Check if transcription is a string or an object
        if hasattr(transcription, 'text'):
            return transcription.text
        return str(transcription)
    except Exception as e:
        logger.error(f"Error in Whisper transcription: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise

def get_recording(recording_id):
    """Get a specific recording by ID"""
    try:
        response = table.get_item(Key={"id": recording_id})
        
        if "Item" not in response:
            return {
                "statusCode": 404,
                "body": json.dumps({"error": "Recording not found"}),
                "headers": CORS_HEADERS
            }
        
        return {
            "statusCode": 200,
            "body": json.dumps(response["Item"]),
            "headers": CORS_HEADERS
        }
    except Exception as e:
        logger.error(f"Error getting recording {recording_id}: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
            "headers": CORS_HEADERS
        }

def list_recordings(user_id):
    """List all recordings for a user"""
    try:
        response = table.scan(
            FilterExpression=Attr("user_id").eq(user_id)
        )
        
        items = response.get("Items", [])
        
        return {
            "statusCode": 200,
            "body": json.dumps(items),
            "headers": CORS_HEADERS
        }
    except Exception as e:
        logger.error(f"Error listing recordings for user {user_id}: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
            "headers": CORS_HEADERS
        }

def generate_summary_in_chunks(text, max_chunk_size=4000):
    """Generate summary from text, splitting into chunks if needed"""
    try:
        if not text:
            return {"title": "無題", "summary": "", "keywords": []}
            
        # If text is short enough, process directly
        if len(text) <= max_chunk_size:
            return generate_summary_from_text(text)
            
        # Split into chunks
        chunks = [text[i:i+max_chunk_size] for i in range(0, len(text), max_chunk_size)]
        logger.info(f"Splitting text into {len(chunks)} chunks for summary generation")
        
        # Generate summary for each chunk
        chunk_summaries = []
        for i, chunk in enumerate(chunks):
            logger.info(f"Generating summary for chunk {i+1}/{len(chunks)}")
            chunk_summary = generate_summary_from_text(chunk)
            chunk_summaries.append(chunk_summary.get("summary", ""))
        
        # Combine chunk summaries
        combined_summary_text = " ".join(chunk_summaries)
        
        # Generate final summary from the combined summaries
        if len(combined_summary_text) > max_chunk_size:
            logger.info("Combined summaries still too large, summarizing again")
            final_summary = generate_summary_from_text(combined_summary_text[:max_chunk_size])
        else:
            final_summary = generate_summary_from_text(combined_summary_text)
            
        return final_summary
    except Exception as e:
        logger.error(f"Error generating summary in chunks: {e}")
        return {"title": "無題", "summary": text[:200] + "..." if len(text) > 200 else text, "keywords": []}

def generate_summary_from_text(text):
    """Generate summary, title and keywords from text using OpenAI"""
    try:
        if not text or len(text.strip()) < 10:
            return {"title": "無題", "summary": "", "keywords": []}
            
        # Extract product and call reason
        extracted_info = extract_product_and_call_reason(text)
        product_name = extracted_info.get("product_name", "")
        call_reason = extracted_info.get("call_reason", "")
        
        # Format the keywords as requested
        keywords = []
        if product_name:
            keywords.append(f"プロダクト＝{product_name}")
        if call_reason:
            keywords.append(f"通話理由 = {call_reason}")
            
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "あなたは会議の録音から要約を生成する専門家です。"},
                {"role": "user", "content": f"以下の文字起こしから、タイトル、要約、キーワードを抽出してください。\n\n{text}"}
            ],
            functions=[
                {
                    "name": "generate_summary",
                    "description": "Generate a summary from meeting transcript",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": "A concise title for the meeting"
                            },
                            "summary": {
                                "type": "string",
                                "description": "A summary of the meeting content"
                            },
                            "keywords": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Key topics or terms from the meeting"
                            }
                        },
                        "required": ["title", "summary", "keywords"]
                    }
                }
            ],
            function_call={"name": "generate_summary"}
        )
        
        function_call = response.choices[0].message.function_call
        if function_call:
            summary_data = json.loads(function_call.arguments)
            # Replace the keywords with our formatted product and call reason
            summary_data["keywords"] = keywords
            return summary_data
        else:
            return {"title": "無題", "summary": "", "keywords": keywords}
    except Exception as e:
        logger.error(f"Error generating summary: {e}")
        # Try to extract product and call reason even in case of error
        try:
            extracted_info = extract_product_and_call_reason(text)
            product_name = extracted_info.get("product_name", "")
            call_reason = extracted_info.get("call_reason", "")
            
            keywords = []
            if product_name:
                keywords.append(f"プロダクト＝{product_name}")
            if call_reason:
                keywords.append(f"通話理由 = {call_reason}")
        except:
            keywords = []
            
        return {"title": "無題", "summary": text[:200] + "..." if len(text) > 200 else text, "keywords": keywords}

def extract_product_and_call_reason(text):
    """
    Extract product name and call reason from text using OpenAI.
    
    Args:
        text (str): The text to analyze
        
    Returns:
        dict: A dictionary containing product_name and call_reason
    """
    try:
        if not text or len(text.strip()) < 10:
            return {"product_name": "", "call_reason": ""}
            
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "あなたは顧客の問い合わせから製品名と問い合わせ理由を特定する専門家です。"},
                {"role": "user", "content": f"以下のテキストから、製品名と問い合わせ理由（クレーム、問い合わせ、返品など）を特定してください。\n\n{text}"}
            ],
            functions=[
                {
                    "name": "extract_info",
                    "description": "Extract product name and call reason from customer inquiry",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "product_name": {
                                "type": "string",
                                "description": "The name of the product mentioned in the text"
                            },
                            "call_reason": {
                                "type": "string",
                                "description": "The reason for the call (e.g., クレーム, 問い合わせ, 返品)"
                            }
                        },
                        "required": ["product_name", "call_reason"]
                    }
                }
            ],
            function_call={"name": "extract_info"}
        )
        
        function_call = response.choices[0].message.function_call
        if function_call:
            extracted_data = json.loads(function_call.arguments)
            return extracted_data
        else:
            return {"product_name": "", "call_reason": ""}
    except Exception as e:
        logger.error(f"Error extracting product and call reason: {e}")
        return {"product_name": "", "call_reason": ""}

def classify_with_keywords(text, product_keywords=None, call_reason_keywords=None):
    """
    Classify text based on keywords to identify product name and call reason.
    
    Args:
        text (str): The text to analyze
        product_keywords (dict, optional): Dictionary mapping product keywords to product names
        call_reason_keywords (dict, optional): Dictionary mapping call reason keywords to call reasons
        
    Returns:
        dict: A dictionary containing product_name and call_reason
    """
    if not text:
        return {"product_name": "", "call_reason": ""}
    
    # Default keyword mappings if none provided
    if product_keywords is None:
        product_keywords = {
            "スーパブレイン3000": "Super Brain 3000",
            "スーパーブレイン3000": "Super Brain 3000",
            "スーパーブレイン": "Super Brain 3000",
            "スーパブレイン": "Super Brain 3000",
            "3000": "Super Brain 3000"
        }
    
    if call_reason_keywords is None:
        call_reason_keywords = {
            "クレーム": "クレーム",
            "返品": "返品",
            "返却": "返品",
            "壊れ": "クレーム",
            "故障": "クレーム",
            "不具合": "クレーム",
            "問題": "クレーム",
            "うるさい": "クレーム",
            "音": "クレーム",
            "弦": "クレーム",
            "正常": "問い合わせ"
        }
    
    # Initialize results
    product_name = ""
    call_reason = ""
    
    # Check for product keywords
    for keyword, name in product_keywords.items():
        if keyword in text:
            product_name = name
            break
    
    # Check for call reason keywords
    for keyword, reason in call_reason_keywords.items():
        if keyword in text:
            call_reason = reason
            break
    
    # If no matches found, try using OpenAI for more advanced extraction
    if not product_name or not call_reason:
        ai_result = extract_product_and_call_reason(text)
        
        # Use AI results only if keyword matching failed
        if not product_name:
            product_name = ai_result.get("product_name", "")
        
        if not call_reason:
            call_reason = ai_result.get("call_reason", "")
    
    return {"product_name": product_name, "call_reason": call_reason}

def debug_step_functions_execution(execution_arn):
    """Debug a Step Functions execution by getting its input/output and history"""
    try:
        step_functions_client = boto3.client('stepfunctions')
        
        # Get execution details
        execution = step_functions_client.describe_execution(
            executionArn=execution_arn
        )
        
        # Get execution history
        history = step_functions_client.get_execution_history(
            executionArn=execution_arn,
            maxResults=20
        )
        
        # Extract key events
        key_events = []
        for event in history['events']:
            if event['type'] in ['ExecutionStarted', 'ExecutionSucceeded', 'ExecutionFailed', 'TaskStateEntered', 'TaskStateExited', 'TaskSubmitted', 'TaskSucceeded', 'TaskFailed']:
                key_events.append({
                    'type': event['type'],
                    'id': event['id'],
                    'timestamp': str(event['timestamp']),
                    'details': {k: v for k, v in event.items() if k not in ['type', 'id', 'timestamp', 'previousEventId']}
                })
        
        return {
            'execution': {
                'name': execution['name'],
                'status': execution['status'],
                'startDate': str(execution['startDate']),
                'stopDate': str(execution.get('stopDate', '')),
                'input': json.loads(execution['input']),
                'output': json.loads(execution.get('output', '{}')),
            },
            'key_events': key_events
        }
    except Exception as e:
        logger.error(f"Error debugging Step Functions execution: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            'error': str(e)
        }

def clean_repeated_phrases(text):
    """異常に繰り返されるフレーズを検出して修正し、文単位で分割する"""
    if not text:
        return text
        
    # 文を分割 (句読点で区切る)
    sentences = re.split(r'([、。,.!?])', text)
    cleaned_sentences = []
    
    # 繰り返し検出のための変数
    last_phrase = ""
    repeat_count = 0
    max_repeats = 2  # 許容する最大繰り返し回数
    
    i = 0
    while i < len(sentences):
        # 文とその後の句読点を取得
        phrase = sentences[i].strip() if i < len(sentences) else ""
        punctuation = sentences[i+1] if i+1 < len(sentences) else ""
        
        if not phrase:
            i += 2  # 句読点も飛ばす
            continue
            
        # 前のフレーズと同じかチェック
        if phrase == last_phrase:
            repeat_count += 1
            # 許容回数以内なら追加
            if repeat_count <= max_repeats:
                cleaned_sentences.append(phrase + punctuation)
        else:
            # 新しいフレーズ
            repeat_count = 0
            last_phrase = phrase
            cleaned_sentences.append(phrase + punctuation)
        
        i += 2  # 次の文と句読点のペアへ
    
    # 結合して返す
    return "".join(cleaned_sentences)

def format_transcription(text):
    """Format transcription text with proper sentence breaks and paragraphs"""
    if not text:
        return text
        
    # First, clean up any repeated phrases
    text = clean_repeated_phrases(text)
    
    # Improve sentence detection for Japanese text
    # Look for sentence endings (。, ?, !, etc.) followed by spaces or other sentence endings
    text = re.sub(r'([。.!?])([^」』）\]）】])', r'\1\n\2', text)
    
    # Also break on long phrases separated by spaces that might be different speakers
    text = re.sub(r'(\S{10,})\s+(\S)', r'\1\n\2', text)
    
    # Handle potential speaker changes or topic changes
    text = re.sub(r'((?:はい|えーと|あの|そうですね|なるほど)[\s,、])', r'\n\1', text)
    
    # Split into paragraphs
    paragraphs = text.split('\n')
    formatted_paragraphs = []
    
    for paragraph in paragraphs:
        if paragraph.strip():
            # Add proper spacing after punctuation for readability
            paragraph = re.sub(r'([。.!?、,])([^\s」』）\]）】])', r'\1 \2', paragraph)
            formatted_paragraphs.append(paragraph.strip())
    
    # Join paragraphs with double newlines
    return "\n\n".join(formatted_paragraphs)

def structure_transcription(text):
    """文字起こしを文単位で構造化する"""
    if not text:
        return []
    
    # 改良: より正確に日本語の文を検出
    # 句読点で区切る (。、!?など)
    pattern = r'([^、。,.!?]+[、。,.!?])'
    sentences = re.findall(pattern, text)
    
    # 構造化された文のリストを作成
    structured_sentences = [
        {
            "text": sentence.strip(),
            "start_time": 0,  # 開始時間は現在不明
            "end_time": 0     # 終了時間は現在不明
        }
        for sentence in sentences if sentence.strip()
    ]
    
    return structured_sentences

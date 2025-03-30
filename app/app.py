import os
import json
import re
import boto3
from functools import wraps
from flask import Flask, Response, stream_with_context, request
import uuid
import time

app = Flask(__name__)

def get_stored_api_key():
    """
    从 Secrets Manager 获取存储的 API key，
    Secrets 格式为 {"bedrock-access-gateway-apikey": "xxxxxxxxxxxxxxxx"}
    """
    secret_name = os.environ.get("AUTH_SECRET_ID", "bedrock-access-gateway")
    app.logger.info(f"Attempting to get secret with name: {secret_name}")
    
    try:
        # 确保设置了正确的区域
        secrets_client = boto3.client(
            "secretsmanager",
            region_name="cn-northwest-1"  # 明确指定宁夏区域
        )
        
        # 获取密钥
        response = secrets_client.get_secret_value(SecretId=secret_name)
        app.logger.info("Successfully retrieved secret from Secrets Manager")
        
        # 解析密钥
        secret_string = response.get("SecretString", "{}")
        secret_json = json.loads(secret_string)
        api_key = secret_json.get("bedrock-access-gateway-apikey")
        
        # 记录结果
        app.logger.info(f"Parsed secret value - Key exists: {api_key is not None}")
        if api_key is None:
            app.logger.error(f"Available keys in secret: {list(secret_json.keys())}")
            
        return api_key
        
    except Exception as e:
        app.logger.error(f"获取Secret失败：{str(e)}")
        # 打印更详细的错误信息
        import traceback
        app.logger.error(f"详细错误：{traceback.format_exc()}")
        return None

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # 从请求头中提取 Authorization 信息，格式： "Bearer ai_key"
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return Response("Unauthorized: Missing or invalid Authorization header", status=401)
        # 提取 Bearer Token
        ai_key = auth_header.split(" ", 1)[1].strip()
        stored_api_key = get_stored_api_key()
        if not stored_api_key or ai_key != stored_api_key:
            return Response("Unauthorized: Invalid ai_key", status=401)
        return f(*args, **kwargs)
    return decorated

# SageMaker Endpoint 名称，通过环境变量设置
SAGEMAKER_ENDPOINT_NAME = os.environ.get("SAGEMAKER_ENDPOINT_NAME", "deepseek-ai-DeepSeek-R1-Distill-Qwen-1-5B-250328-0051")
sagemaker_runtime = boto3.client("sagemaker-runtime")

@app.route('/v1/chat/completions', methods=['POST'])
@requires_auth
def chat_completions():
    """
    接收 OpenAI 兼容请求，根据 stream 参数决定是否返回流式响应。
    """
    try:
        body = request.get_json(force=True)
    except Exception as e:
        return Response("Invalid JSON", status=400)
    
    messages = body.get("messages", [])
    stream = body.get("stream", False)  # 获取 stream 参数，默认为 False
    
    payload = {
        "messages": messages,
        "max_tokens": body.get("max_tokens", 1024),
        "stream": stream  # 传递 stream 参数给 SageMaker endpoint
    }
    
    if stream:
        # 流式响应逻辑
        response = sagemaker_runtime.invoke_endpoint_with_response_stream(
            EndpointName=SAGEMAKER_ENDPOINT_NAME,
            ContentType='application/json',
            Body=json.dumps(payload)
        )
        
        def generate():
            buffer = ""
            for t in response['Body']:
                chunk_bytes = t["PayloadPart"]["Bytes"]
                chunk_str = chunk_bytes.decode('utf-8')
                buffer += chunk_str
                last_idx = 0
                for match in re.finditer(r'^data:\s*(.+?)(\n\n)', buffer, flags=re.MULTILINE | re.DOTALL):
                    try:
                        data_str = match.group(1).strip()
                        if data_str:
                            data = json.loads(data_str)
                            last_idx = match.span()[1]
                            delta = data.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield f"data: {json.dumps({'content': content})}\n\n"
                    except Exception:
                        continue
                buffer = buffer[last_idx:]
        
        return Response(stream_with_context(generate()), mimetype='text/event-stream')
    
    else:
        # 非流式响应逻辑
        response = sagemaker_runtime.invoke_endpoint(
            EndpointName=SAGEMAKER_ENDPOINT_NAME,
            ContentType='application/json',
            Body=json.dumps(payload)
        )
        
        # 解析响应并修改模型名称
        response_body = json.loads(response['Body'].read())
        response_body["model"] = SAGEMAKER_ENDPOINT_NAME  # 使用 endpoint 名称替换默认的模型路径
        
        return Response(
            json.dumps(response_body),
            status=200,
            mimetype="application/json"
        )

@app.route('/health', methods=['GET'])
@requires_auth
def health():
    """
    返回 {"status": "ok"}， HTTP 状态码 200。
    """
    return Response(
        json.dumps({"status": "ok"}),
        status=200,
        mimetype="application/json"
    )

@app.route('/v1/models', methods=['GET'])
@requires_auth
def list_models():
    """
    列出本账户下所有的 SageMaker 实时推理 Endpoint 及其状态，
    返回 JSON 格式的结果。
    """
    sagemaker_client = boto3.client("sagemaker")
    all_endpoints = []
    
    response = sagemaker_client.list_endpoints(MaxResults=100)
    all_endpoints.extend(response.get("Endpoints", []))
    
    while "NextToken" in response:
        response = sagemaker_client.list_endpoints(
            MaxResults=100,
            NextToken=response["NextToken"]
        )
        all_endpoints.extend(response.get("Endpoints", []))
    
    results = []
    for ep in all_endpoints:
        results.append({
            "EndpointName": ep.get("EndpointName"),
            "EndpointStatus": ep.get("EndpointStatus")
        })
    
    return Response(
        json.dumps(results, ensure_ascii=False),
        status=200,
        mimetype="application/json"
    )

@app.route('/ping', methods=['GET'])
def ping():
    """
    无需认证的健康检查接口，专门给 ALB 使用。
    返回 {"status": "ok"}， HTTP 状态码 200。
    """
    return Response(
        json.dumps({"status": "ok"}),
        status=200,
        mimetype="application/json"
    )

@app.route('/debug-auth', methods=['GET'])
def debug_auth():
    """
    临时的调试端点，用于验证认证逻辑
    """
    auth_header = request.headers.get("Authorization", "")
    received_key = auth_header.split(" ", 1)[1].strip() if auth_header.startswith("Bearer ") else ""
    stored_key = get_stored_api_key()
    
    debug_info = {
        "received_auth_header": auth_header,
        "received_key": received_key,
        "received_key_length": len(received_key),
        "received_key_repr": repr(received_key),
        "stored_key": stored_key,
        "stored_key_length": len(stored_key) if stored_key else 0,
        "stored_key_repr": repr(stored_key) if stored_key else None,
        "keys_equal": received_key == stored_key
    }
    
    return Response(
        json.dumps(debug_info, indent=2),
        status=200,
        mimetype="application/json"
    )

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080)

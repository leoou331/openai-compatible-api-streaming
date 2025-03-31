import os
import json
import re
import boto3
from functools import wraps
from flask import Flask, Response, stream_with_context, request
import uuid
import time
import logging

app = Flask(__name__)

# 设置日志级别
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 打印环境变量
logger.info(f"环境变量 SAGEMAKER_ENDPOINT_NAME: {os.environ.get('SAGEMAKER_ENDPOINT_NAME', 'NOT SET')}")

# 使用环境变量或默认值
SAGEMAKER_ENDPOINT_NAME = os.environ.get("SAGEMAKER_ENDPOINT_NAME", "deepseek-ai-DeepSeek-R1-Distill-Qwen-1-5B-250326-0342")
logger.info(f"实际使用的 SAGEMAKER_ENDPOINT_NAME: {SAGEMAKER_ENDPOINT_NAME}")

# API 密钥缓存变量
_API_KEY_CACHE = None
_API_KEY_TIMESTAMP = 0
_API_KEY_TTL = int(os.environ.get("API_KEY_CACHE_TTL", "3600"))

def get_stored_api_key():
    """
    从 Secrets Manager 获取存储的 API key，
    Secrets 格式为 {"bedrock-access-gateway-apikey": "xxxxxxxxxxxxxxxx"}
    
    实现了缓存机制，避免频繁调用 Secrets Manager API
    """
    global _API_KEY_CACHE, _API_KEY_TIMESTAMP
    current_time = time.time()

    # 如果缓存仍然有效，直接返回缓存的密钥
    if _API_KEY_CACHE and (current_time - _API_KEY_TIMESTAMP) < _API_KEY_TTL:
        app.logger.debug("Using cached API key")
        return _API_KEY_CACHE

    # 缓存无效，需要重新获取密钥
    app.logger.info("Fetching new API key from Secrets Manager")
    secret_name = os.environ.get("AUTH_SECRET_ID", "bedrock-access-gateway")  # 通过环境变量配置SecretId
    
    try:
        # 确保设置了正确的区域
        secrets_client = boto3.client(
            "secretsmanager",
            region_name=os.environ.get("AWS_REGION", "cn-northwest-1")
        )
        
        # 获取密钥
        response = secrets_client.get_secret_value(SecretId=secret_name)
        secret_string = response.get("SecretString", "{}")
        secret_json = json.loads(secret_string)
        api_key = secret_json.get("bedrock-access-gateway-apikey")
        
        # 更新缓存
        if api_key:
            _API_KEY_CACHE = api_key
            _API_KEY_TIMESTAMP = current_time
            app.logger.info("Successfully updated API key cache")
        else:
            app.logger.error(f"API key not found in secret {secret_name}")
            
        return api_key
    except Exception as e:
        app.logger.error(f"获取Secret失败：{str(e)}")
        # 如果获取失败但有缓存，可以考虑使用过期的缓存作为回退
        if _API_KEY_CACHE:
            app.logger.warning("Using expired cached API key as fallback")
            return _API_KEY_CACHE
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
        app.logger.error(f"JSON parsing error: {str(e)}")
        return Response(f"Invalid JSON: {str(e)}", status=400)
    
    # 验证必需字段
    messages = body.get("messages", [])
    if not messages or not isinstance(messages, list):
        return Response("Invalid messages format: must be a non-empty list", status=400)
    
    # 验证消息格式
    for i, msg in enumerate(messages):
        if not isinstance(msg, dict):
            return Response(f"Message at index {i} is not an object", status=400)
        
        # 检查必需字段
        if "role" not in msg:
            return Response(f"Message at index {i} missing required field 'role'", status=400)
        
        if "content" not in msg:
            return Response(f"Message at index {i} missing required field 'content'", status=400)
        
        # 验证角色类型
        valid_roles = ["system", "user", "assistant", "function"]
        if msg["role"] not in valid_roles:
            return Response(f"Invalid role '{msg['role']}' at index {i}. Must be one of: {', '.join(valid_roles)}", status=400)
    
    # 验证其他参数
    stream = body.get("stream", False)
    if not isinstance(stream, bool):
        return Response("Invalid 'stream' parameter: must be a boolean", status=400)
    
    max_tokens = body.get("max_tokens", 1024)
    if not isinstance(max_tokens, int) or max_tokens <= 0:
        return Response("Invalid 'max_tokens' parameter: must be a positive integer", status=400)
    
    # 构建有效的负载
    payload = {
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": stream
    }
    
    # 添加可选参数（如果存在）
    if "temperature" in body:
        temp = body["temperature"]
        if not (isinstance(temp, (int, float)) and 0 <= temp <= 2):
            return Response("Invalid 'temperature' parameter: must be a number between 0 and 2", status=400)
        payload["temperature"] = temp
    
    # 继续处理流式或非流式响应
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
                try:
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
                except Exception as e:
                    app.logger.error(f"Error processing stream chunk: {str(e)}")
                    # 可能的错误恢复策略或继续处理其他块
                    continue
        
        return Response(stream_with_context(generate()), mimetype='text/event-stream')
    
    else:
        # 非流式响应逻辑
        try:
            response = sagemaker_runtime.invoke_endpoint(
                EndpointName=SAGEMAKER_ENDPOINT_NAME,
                ContentType='application/json',
                Body=json.dumps(payload)
            )
        except Exception as e:
            app.logger.error(f"SageMaker endpoint invocation error: {str(e)}")
            return Response(f"Error invoking model: {str(e)}", status=500)
        
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


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080)

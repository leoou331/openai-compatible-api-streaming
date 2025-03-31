#!/usr/bin/env python3
import os
import re
import sys
from openai import OpenAI

# 设置更好的调试输出
def log(message):
    """带时间戳的日志输出，并立即刷新到终端"""
    import datetime
    timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{timestamp}] {message}", flush=True)

log("脚本开始执行")

# 从环境变量获取配置
base_url = os.environ.get("OPENAI_BASE_URL", "")
api_key = os.environ.get("OPENAI_API_KEY", "")
model = os.environ.get("MODEL", "")

log(f"环境变量检查:")
log(f"OPENAI_BASE_URL = {base_url}")
log(f"MODEL = {model}")
log(f"OPENAI_API_KEY = {'已设置' if api_key else '未设置'}")

# 检查环境变量
missing_vars = []
if not base_url:
    missing_vars.append("OPENAI_BASE_URL")
if not api_key:
    missing_vars.append("OPENAI_API_KEY")
if not model:
    missing_vars.append("MODEL")

if missing_vars:
    log(f"错误: 缺少以下环境变量: {', '.join(missing_vars)}")
    sys.exit(1)

# 验证 base_url 格式
if not re.match(r'^https?://', base_url):
    log(f"警告: OPENAI_BASE_URL 不包含协议前缀，自动添加 'https://'")
    base_url = f"https://{base_url}"
    log(f"修正后 URL: {base_url}")

# 验证 base_url 末尾是否有 /v1
if not base_url.endswith('/v1'):
    if base_url.endswith('/'):
        base_url += 'v1'
    else:
        base_url += '/v1'
    log(f"已添加 '/v1' 到 URL 末尾: {base_url}")

log("初始化 OpenAI 客户端...")
try:
    client = OpenAI(
        base_url=base_url,
        api_key=api_key
    )
    
    log(f"创建聊天完成请求，模型: {model}")
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": "Hello!"}
        ],
        temperature=0.7,
        stream=True,
        max_tokens=256
    )
    
    log("开始接收流式响应...")
    # 处理流式响应
    full_content = ""
    for chunk in completion:
        if hasattr(chunk, 'content'):
            content = chunk.content
            if content:
                full_content += content
                print(content, end='', flush=True)
    
    print("\n\n完整响应:", full_content)
    
except Exception as e:
    log(f"发生错误: {type(e).__name__}: {str(e)}")
    import traceback
    log("详细错误信息:")
    traceback.print_exc()

log("脚本执行完毕")

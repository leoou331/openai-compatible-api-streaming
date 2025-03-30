#!/usr/bin/env python3
import os
from openai import OpenAI

# 从环境变量获取配置
base_url = os.environ.get("OPENAI_BASE_URL")
api_key = os.environ.get("OPENAI_API_KEY")
model = os.environ.get("MODEL")
if not base_url or not api_key or not model:
    raise ValueError("请设置环境变量 OPENAI_BASE_URL 和 OPENAI_API_KEY 和 MODEL")

# 配置你的OpenAI兼容API Gateway地址和鉴权token
client = OpenAI(
    base_url=base_url,
    api_key=api_key
)

# 发起请求
completion = client.chat.completions.create(
    model=model,
    messages=[
        {"role": "user", "content": "Hello!"}
    ],
    temperature=0.7,
    stream=True,
    max_tokens=256
)

# 处理流式响应
full_content = ""
for chunk in completion:
    if hasattr(chunk, 'content'):
        content = chunk.content
        if content:
            full_content += content
            print(content, end='', flush=True)

print("\n\n完整响应:", full_content)

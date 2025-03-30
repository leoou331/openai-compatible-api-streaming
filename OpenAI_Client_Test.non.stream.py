#!/usr/bin/env python3
import os
from openai import OpenAI

# 从环境变量获取配置
base_url = os.environ.get("OPENAI_BASE_URL")
api_key = os.environ.get("OPENAI_API_KEY")
model = os.environ.get("MODEL")
if not base_url or not api_key or not model:
    raise ValueError("请设置环境变量 OPENAI_BASE_URL 和 OPENAI_API_KEY 和 MODEL")

# 配置OpenAI客户端
client = OpenAI(
    base_url=base_url,
    api_key=api_key
)

# 发起非流式请求
completion = client.chat.completions.create(
    model=model,
    messages=[
        {"role": "user", "content": "Hello!"}
    ],
    temperature=0.7,
    stream=False,  # 设置为 False 使用非流式响应
    max_tokens=256
)

# 打印响应
print("Response ID:", completion.id)
print("Model:", completion.model)
print("Created:", completion.created)
print("Choices:", len(completion.choices))
print("Content:", completion.choices[0].message.content)
print("Usage:", completion.usage)

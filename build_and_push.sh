#!/bin/bash

# 1. 首先检查所有必需的环境变量
missing_vars=""

if [ -z "${AWS_REGION}" ]; then
    missing_vars="${missing_vars} AWS_REGION"
fi

if [ -z "${AUTH_SECRET_ID}" ]; then
    missing_vars="${missing_vars} AUTH_SECRET_ID"
fi

if [ -z "${API_KEY_CACHE_TTL}" ]; then
    missing_vars="${missing_vars} API_KEY_CACHE_TTL"
fi

if [ -z "${AWS_ACCOUNT_ID}" ]; then
    missing_vars="${missing_vars} AWS_ACCOUNT_ID"
fi

# 如果有缺少的环境变量，输出错误信息并退出
if [ ! -z "${missing_vars}" ]; then
    echo "错误: 以下环境变量未设置:${missing_vars}"
    echo "请设置这些环境变量后再运行脚本。"
    exit 1
fi

# 2. 环境变量检查通过后，才执行 Docker 相关命令

# 登录到 ECR
echo "登录到 ECR..."
aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com.cn

# 构建 Docker 镜像
echo "构建 Docker 镜像..."
docker build -t openai-compatible-streaming:latest .

# 标记镜像
echo "标记镜像..."
docker tag openai-compatible-streaming:latest ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com.cn/openai-compatible-streaming:latest

# 推送镜像到 ECR
echo "推送镜像到 ECR..."
docker push ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com.cn/openai-compatible-streaming:latest

echo "完成! 镜像已推送到: ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com.cn/openai-compatible-streaming:latest"

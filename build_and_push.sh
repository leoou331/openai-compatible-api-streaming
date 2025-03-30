# 登录到 ECR（根据实际命令）
aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com

# 在项目根目录下构建 Docker 镜像
docker build -t openai-compatible-streaming:latest .

# 标记镜像
docker tag openai-compatible-streaming:latest ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/openai-compatible-streaming:latest

# 推送镜像到 ECR
docker push ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/openai-compatible-streaming:latest

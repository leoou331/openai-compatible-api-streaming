# OpenAI 兼容的 SageMaker 流式响应 API

这个项目提供了一个与 OpenAI API 兼容的接口，用于访问部署在 Amazon SageMaker 上的大语言模型。支持流式和非流式响应，完全兼容 OpenAI 的 API 格式。

## 功能特点

- 完全兼容 OpenAI API 格式
- 支持流式响应（SSE）和非流式响应
- 支持 Bearer Token 认证
- 使用 AWS Secrets Manager 管理 API 密钥
- 健康检查接口支持 ALB 集成
- 支持查看可用模型列表

## 前置条件

在开始之前，您需要：

1. 设置环境变量
   
   创建一个 `.env` 文件，包含以下内容：
   ```bash
   # OpenAI 兼容 API 地址，格式为 "http://<ALB ADDRESS>/v1"
   # 部署完成后，将 <ALB ADDRESS> 替换为实际的 ALB 地址
   export OPENAI_BASE_URL="http://<ALB ADDRESS>/v1" 
   
   # API 密钥，与 Secrets Manager 中设置的 bedrock-access-gateway-apikey 值相同
   export OPENAI_API_KEY="xxxxxxxxxxxxxxxxxxxxxxxxxxx" 
   
   # SageMaker 端点名称，例如 "deepseek-ai-DeepSeek-R1-Distill-Qwen-1-5B"
   export MODEL="<Sagemaker Endpoint Name>" 
   
   # AWS 区域，例如 "cn-northwest-1"
   export AWS_REGION="<AWS Region>"
   
   # AWS 账号 ID，12 位数字
   export AWS_ACCOUNT_ID="<AWS Account ID>"
   ```

2. 加载环境变量
   ```bash
   source .env
   ```

3. **重要**：修改 Dockerfile 中的环境变量
   
   在构建 Docker 镜像前，请确保 Dockerfile 中的环境变量与您的实际区域匹配。打开 Dockerfile 并更新以下行：
   
   ```dockerfile
   # 设置AWS区域环境变量
   ENV AWS_DEFAULT_REGION=cn-north-1  # 修改为您的实际区域，例如 cn-northwest-1
   ENV AWS_REGION=cn-north-1          # 修改为您的实际区域，例如 cn-northwest-1
   ENV AUTH_SECRET_ID=bedrock-access-gateway  # 如果使用不同的密钥名称，请修改此处
   ```
   
   **注意**：确保这些值与您的实际环境一致，特别是区域设置，否则将无法访问 Secrets Manager 和 SageMaker 端点。

## API 端点

- `/v1/chat/completions` - 聊天补全接口
- `/v1/models` - 列出可用的模型
- `/health` - 认证健康检查
- `/ping` - 无认证健康检查（用于 ALB）

## 环境要求

- Python 3.9+
- AWS EKS 集群
- AWS Secrets Manager
- Amazon SageMaker 端点

## 配置说明

### 环境变量

- `SAGEMAKER_ENDPOINT_NAME` - SageMaker 端点名称
- `AUTH_SECRET_ID` - Secrets Manager 中的密钥 ID
- `AWS_DEFAULT_REGION` - AWS 区域（例如：cn-northwest-1）

### Secrets Manager 配置

在 AWS Secrets Manager 中创建密钥，格式如下：
```json
{
    "bedrock-access-gateway-apikey": "your-api-key"
}
```

## 在 EKS 中部署

### 1. 构建 Docker 镜像
项目提供了一个简单的脚本 `build_and_push.sh` 来构建和推送 Docker 镜像。使用前需要修改脚本中的 AWS 账号 ID 和区域信息。

```bash
# 使构建脚本可执行
chmod +x build_and_push.sh

# 运行构建脚本
./build_and_push.sh
```

该脚本会使用环境变量中的 `AWS_ACCOUNT_ID` 和 `AWS_REGION` 值，请确保您已经运行了 `source .env`。

### 2. 创建 Kubernetes 资源

#### 创建命名空间
```yaml
# namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: ai-service
```

#### 创建 ConfigMap
```yaml
# configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: openai-compatible-api-config
  namespace: ai-service
data:
  SAGEMAKER_ENDPOINT_NAME: "${MODEL}"
  AUTH_SECRET_ID: "bedrock-access-gateway"
```

#### 创建 Service Account
```yaml
# serviceaccount.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: openai-compatible-api
  namespace: ai-service
  annotations:
    eks.amazonaws.com/role-arn: arn:aws-cn:iam::${AWS_ACCOUNT_ID}:role/openai-compatible-api-role
```

#### 创建 Deployment
```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: openai-compatible-api
  namespace: ai-service
spec:
  replicas: 2
  selector:
    matchLabels:
      app: openai-compatible-api
  template:
    metadata:
      labels:
        app: openai-compatible-api
    spec:
      serviceAccountName: openai-compatible-api
      containers:
      - name: api
        image: ${AWS_ACCOUNT_ID}.dkr.ecr.cn-northwest-1.amazonaws.com.cn/openai-compatible-streaming:latest
        ports:
        - containerPort: 8080
        envFrom:
        - configMapRef:
            name: openai-compatible-api-config
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "1Gi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /ping
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 10
```

#### 创建 Service
```yaml
# service.yaml
apiVersion: v1
kind: Service
metadata:
  name: openai-compatible-api
  namespace: ai-service
spec:
  ports:
  - port: 80
    targetPort: 8080
  selector:
    app: openai-compatible-api
```

#### 创建 Ingress
```yaml
# ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: openai-compatible-api
  namespace: ai-service
  annotations:
    kubernetes.io/ingress.class: alb
    alb.ingress.kubernetes.io/scheme: internet-facing
spec:
  rules:
  - http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: openai-compatible-api
            port:
              number: 80
```

### 3. 部署应用

```bash
kubectl apply -f namespace.yaml
kubectl apply -f configmap.yaml
kubectl apply -f serviceaccount.yaml
kubectl apply -f deployment.yaml
kubectl apply -f service.yaml
kubectl apply -f ingress.yaml
```

## 使用示例

### Python 客户端

本项目提供了两个测试脚本，可以帮助您验证服务是否正常工作：

1. **流式响应测试**
   
   使用 `OpenAI_Client_Test.py` 测试流式输出：
   ```bash
   # 确保环境变量已加载
   source .env
   
   # 使脚本可执行
   chmod +x OpenAI_Client_Test.py
   
   # 运行测试
   ./OpenAI_Client_Test.py
   ```
   
   这个脚本会连接到您的 API，发送一个简单的问候，并实时显示流式响应。

2. **非流式响应测试**
   
   使用 `OpenAI_Client_Test.non.stream.py` 测试非流式输出：
   ```bash
   # 确保环境变量已加载
   source .env
   
   # 使脚本可执行
   chmod +x OpenAI_Client_Test.non.stream.py
   
   # 运行测试
   ./OpenAI_Client_Test.non.stream.py
   ```
   
   这个脚本会返回完整的响应，包括元数据如响应 ID、使用的 token 数量等。

这两个脚本都会从环境变量中读取配置，确保您已经正确设置了 `.env` 文件并执行了 `source .env` 命令。

### 自定义客户端示例

如果您想自己编写客户端，可以参考以下代码：

```python
import os
from openai import OpenAI

client = OpenAI(
    base_url=os.environ["OPENAI_BASE_URL"],
    api_key=os.environ["OPENAI_API_KEY"]
)

# 非流式请求
completion = client.chat.completions.create(
    model=os.environ["MODEL"],  # 使用环境变量中的模型名称
    messages=[{"role": "user", "content": "Hello!"}],
    stream=False
)

print(completion.choices[0].message.content)

# 流式请求
stream = client.chat.completions.create(
    model=os.environ["MODEL"],  # 使用环境变量中的模型名称
    messages=[{"role": "user", "content": "Hello!"}],
    stream=True
)

for chunk in stream:
    if hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

**注意**：确保安装了 OpenAI Python 客户端：
```bash
pip install openai
```

## IAM 权限要求

服务账号需要以下权限：
- `sagemaker:InvokeEndpoint`
- `secretsmanager:GetSecretValue`

## 监控和日志

- 应用日志通过 CloudWatch Logs 收集
- 可以通过 CloudWatch Metrics 监控 API 调用次数和延迟
- ALB 访问日志记录在 S3 bucket 中

## 安全考虑

- 所有 API 调用都需要有效的 Bearer Token
- 密钥存储在 AWS Secrets Manager 中
- 使用 HTTPS 进行传输加密
- 容器以非 root 用户运行

## 项目结构
```
openai-compatible-api-streaming/
├── README.md               # 项目说明文档
├── app/                    # 应用代码目录
│   └── app.py              # 主应用代码，包含 API 实现
├── build_and_push.sh       # Docker 镜像构建和推送脚本
├── dockerfile              # Docker 构建配置文件
├── OpenAI_Client_Test.py           # 流式响应测试客户端
└── OpenAI_Client_Test.non.stream.py # 非流式响应测试客户端
```

### 文件说明

- **README.md**: 项目文档，包含安装、配置和使用说明
- **app/app.py**: 主要应用代码，实现了 OpenAI 兼容的 API 接口
  - 包含认证逻辑
  - 实现了流式和非流式响应处理
  - 提供了模型列表查询功能
  - 包含健康检查端点
- **build_and_push.sh**: 自动构建和推送 Docker 镜像的脚本
  - 使用环境变量中的账号和区域信息
  - 处理 ECR 登录、构建和推送过程
- **dockerfile**: Docker 镜像构建配置
  - 基于 Python 3.9 slim 镜像
  - 配置环境变量和依赖项
  - 设置应用入口点
- **OpenAI_Client_Test.py**: 流式响应测试脚本
  - 使用环境变量获取配置
  - 演示如何处理流式 API 响应
- **OpenAI_Client_Test.non.stream.py**: 非流式响应测试脚本
  - 使用环境变量获取配置
  - 演示如何处理标准 API 响应和元数据
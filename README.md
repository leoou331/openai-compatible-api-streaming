# OpenAI Compatible API with SageMaker Streaming

这个项目实现了一个与OpenAI API兼容的服务，使用Amazon SageMaker作为后端来生成文本响应。服务支持流式响应，可以实时将生成内容返回给客户端。

## 功能特点

- 与OpenAI API兼容，易于与现有工具集成
- 支持流式响应 (Server-Sent Events)
- API密钥认证
- 使用Amazon SageMaker作为后端推理服务
- 支持多种部署方式 (Docker, ECS, EKS)

## 环境要求

- Python 3.9+
- AWS账号及相关权限
- Docker (用于容器化部署)
- SageMaker端点已配置

## 安装与部署

### 1. 环境变量配置

在项目根目录创建一个`.env`文件，设置以下环境变量：

```bash
# 客户端测试使用的环境变量
export OPENAI_BASE_URL="http://<ALB ADDRESS>/v1"  # API服务的负载均衡器地址
export OPENAI_API_KEY="xxxxxxxxxxxxxxxxxxxxxxxxxxx"  # 调用API的密钥

# 服务端配置使用的环境变量
export API_KEY_CACHE_TTL="3600"  # API密钥缓存时间，单位为秒
export AUTH_SECRET_ID="bedrock-access-gateway"  # AWS Secret Manager中存储API密钥的Secret ID
export MODEL="deepseek-ai-DeepSeek-R1-Distill-Qwen-1-5B-250326-0342"  # SageMaker端点名称
export AWS_REGION="cn-northwest-1"  # AWS区域
export AWS_ACCOUNT_ID="104946057020"  # AWS账户ID
```

**重要提示**：确保`.env`文件不要提交到代码仓库中，建议将其添加到`.gitignore`文件中。

### 2. 构建和推送Docker镜像

在构建Docker镜像前，先加载环境变量：

```bash
source .env
./build_and_push.sh
```

这个脚本会:
- 更新Dockerfile中的环境变量，特别是`SAGEMAKER_ENDPOINT_NAME`将被设置为环境变量`MODEL`的值
- 构建Docker镜像
- 推送镜像到Amazon ECR

### 3. 部署服务

#### 在ECS上部署

```bash
aws ecs update-service --cluster openai-compatible-api --service openai-compatible-api --task-definition streaming-service:3 --force-new-deployment
```

#### 在EKS上部署

1. **准备Kubernetes清单文件**

   创建一个名为`deployment.yaml`的文件：

   ```yaml
   apiVersion: apps/v1
   kind: Deployment
   metadata:
     name: openai-compatible-api
     namespace: openai-api
     labels:
       app: openai-compatible-api
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
         containers:
         - name: api-container
           image: ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/openai-compatible-api:latest
           ports:
           - containerPort: 5000
           resources:
             requests:
               memory: "512Mi"
               cpu: "0.5"
             limits:
               memory: "1Gi"
               cpu: "1"
           env:
           - name: AWS_REGION
             value: "${AWS_REGION}"
           - name: AUTH_SECRET_ID
             value: "${AUTH_SECRET_ID}"
           - name: API_KEY_CACHE_TTL
             value: "${API_KEY_CACHE_TTL}"
           - name: SAGEMAKER_ENDPOINT_NAME
             value: "${MODEL}"
           readinessProbe:
             httpGet:
               path: /health
               port: 5000
             initialDelaySeconds: 5
             periodSeconds: 10
   ```

   创建一个名为`service.yaml`的文件：

   ```yaml
   apiVersion: v1
   kind: Service
   metadata:
     name: openai-compatible-api
     namespace: openai-api
   spec:
     selector:
       app: openai-compatible-api
     ports:
     - port: 80
       targetPort: 5000
     type: LoadBalancer
   ```

2. **创建命名空间**

   ```bash
   kubectl create namespace openai-api
   ```

3. **部署应用**

   首先，使用环境变量填充Kubernetes清单：

   ```bash
   source .env
   envsubst < deployment.yaml > deployment_filled.yaml
   ```

   然后应用配置：

   ```bash
   kubectl apply -f deployment_filled.yaml
   kubectl apply -f service.yaml
   ```

4. **验证部署**

   ```bash
   kubectl get pods -n openai-api
   kubectl get services -n openai-api
   ```

5. **获取负载均衡器地址**

   ```bash
   kubectl get service openai-compatible-api -n openai-api
   ```
   
   从输出中找到`EXTERNAL-IP`字段，这就是服务的访问地址。更新`.env`文件中的`OPENAI_BASE_URL`为此地址：
   
   ```bash
   export OPENAI_BASE_URL="http://<EXTERNAL-IP>/v1"
   ```

6. **查看日志**

   ```bash
   kubectl logs -f deployment/openai-compatible-api -n openai-api
   ```

7. **扩展部署**

   如需扩展实例数量：

   ```bash
   kubectl scale deployment openai-compatible-api -n openai-api --replicas=3
   ```

8. **更新部署**

   当有新版本的Docker镜像时：

   ```bash
   kubectl set image deployment/openai-compatible-api -n openai-api api-container=${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/openai-compatible-api:latest
   ```

9. **IAM角色配置**

   确保EKS节点有权访问ECR、SageMaker和Secrets Manager。可以使用IAM角色策略或服务账户：

   ```yaml
   apiVersion: v1
   kind: ServiceAccount
   metadata:
     name: openai-api-sa
     namespace: openai-api
     annotations:
       eks.amazonaws.com/role-arn: arn:aws:iam::${AWS_ACCOUNT_ID}:role/openai-api-role
   ```

   然后在部署中使用此服务账户：

   ```yaml
   spec:
     serviceAccountName: openai-api-sa
   ```

#### 使用Helm部署到EKS（可选）

如果您使用Helm管理Kubernetes应用，可以创建一个Helm chart:

1. **创建Helm chart**

   ```bash
   helm create openai-api
   ```

2. **自定义values.yaml**

   修改`values.yaml`文件，设置镜像、环境变量等。

3. **安装chart**

   ```bash
   helm install openai-api ./openai-api -n openai-api
   ```

4. **升级chart**

   ```bash
   helm upgrade openai-api ./openai-api -n openai-api
   ```

## 使用方法

### 测试API

项目包含一个测试脚本`OpenAI_Client_Test.debug.py`，可用于验证API的功能：

1. 首先加载环境变量：

```bash
source .env
```

2. 运行测试脚本：

```bash
python OpenAI_Client_Test.debug.py
```

脚本会使用环境变量中设置的`OPENAI_BASE_URL`、`OPENAI_API_KEY`和`MODEL`，发送一个简单的问候消息"Hello!"，并以流式方式接收和显示响应。

### 使用OpenAI客户端库

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://<ALB ADDRESS>/v1",  # 使用您的API端点URL
    api_key="xxxxxxxxxxxxxxxxxxxxxxxxxxx"  # 使用您的API密钥
)

# 流式请求
completion = client.chat.completions.create(
    model="deepseek-ai-DeepSeek-R1-Distill-Qwen-1-5B-250326-0342",  # 使用您配置的模型名称
    messages=[
        {"role": "user", "content": "Tell me a story about cloud computing"}
    ],
    temperature=0.7,
    stream=True
)

for chunk in completion:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)

# 非流式请求
response = client.chat.completions.create(
    model="deepseek-ai-DeepSeek-R1-Distill-Qwen-1-5B-250326-0342",
    messages=[
        {"role": "user", "content": "What is machine learning?"}
    ],
    temperature=0.7
)

print(response.choices[0].message.content)
```

## 故障排除

### 常见问题

1. **SageMaker端点不存在错误**
   
   确保客户端请求中使用的模型名称与服务器上配置的SageMaker端点名称一致。错误可能如下所示：
   ```
   botocore.errorfactory.ValidationError: An error occurred (ValidationError) when calling the InvokeEndpointWithResponseStream operation: Endpoint deepseek-ai-DeepSeek-R1-Distill-Qwen-1-5B-250328-0051 of account 104946057020 not found.
   ```
   
   可通过以下方式解决：
   - 在`.env`文件中更新`MODEL`变量，使其与实际可用的SageMaker端点名称一致
   - 确保构建Docker镜像时已正确设置`MODEL`环境变量
   - 在部署后验证容器内环境变量是否正确应用

2. **认证失败**
   
   检查API密钥是否正确，以及AWS Secrets Manager中是否存储了相应的密钥信息。

3. **Docker构建错误**
   
   确保`requirements.txt`文件存在且格式正确。如果看到以下错误：
   ```
   ERROR: Could not open requirements file: [Errno 2] No such file or directory: 'requirements.txt'
   ```
   
   请在项目根目录创建一个`requirements.txt`文件，每行包含一个依赖包名：
   ```
   flask
   boto3
   gunicorn
   eventlet
   ```

## 安全注意事项

- API密钥应妥善保存，不要硬编码在应用程序中
- 使用HTTPS保护API通信
- 定期轮换API密钥
- 不要将包含敏感信息的`.env`文件提交到代码仓库

## 贡献

欢迎提交问题和拉取请求。

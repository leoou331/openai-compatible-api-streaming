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
export AUTH_SECRET_ID="<AWS Secret Manager Secret ID for API Key>"  # AWS Secret Manager中存储API密钥的Secret ID
export MODEL="<Sagemaker Endpoint Name>"  # SageMaker端点名称
export AWS_REGION="<AWS REGION>"  # AWS区域
export AWS_ACCOUNT_ID="<AWS Account ID>"  # AWS账户ID
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

ECS部署涉及多个步骤，包括创建集群、任务定义、服务和负载均衡器设置。以下是完整的部署流程：

1. **创建ECS集群**

   ```bash
   aws ecs create-cluster --cluster-name openai-compatible-api
   ```

2. **创建ALB (Application Load Balancer)**

   首先，创建负载均衡器：

   ```bash
   aws elbv2 create-load-balancer \
     --name openai-api-alb \
     --subnets subnet-05d93b5af94148ba1 subnet-03442d240c68331e7 subnet-0eee54d7733f12c28 \
     --security-groups sg-005ac3befca508cfc \
     --scheme internet-facing \
     --type application
   ```

   记下返回的ALB ARN和DNS名称。

3. **创建目标组**

   ```bash
   aws elbv2 create-target-group \
     --name streaming-target-group \
     --protocol HTTP \
     --port 8080 \
     --vpc-id vpc-xxxxxxxx \
     --target-type ip \
     --health-check-path /ping \
     --health-check-interval-seconds 30
   ```

   记下返回的目标组ARN。

4. **创建监听器**

   ```bash
   aws elbv2 create-listener \
     --load-balancer-arn <ALB-ARN> \
     --protocol HTTP \
     --port 80 \
     --default-actions Type=forward,TargetGroupArn=<TARGET-GROUP-ARN>
   ```

5. **创建任务执行IAM角色**

   这个角色允许ECS任务拉取ECR镜像、访问CloudWatch日志等。如果还没有此角色，请创建：

   ```bash
   # 创建角色信任策略文件
   cat > task-execution-role-trust-policy.json << EOF
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Principal": {
           "Service": "ecs-tasks.amazonaws.com"
         },
         "Action": "sts:AssumeRole"
       }
     ]
   }
   EOF

   # 创建角色
   aws iam create-role \
     --role-name ecsTaskExecutionRole \
     --assume-role-policy-document file://task-execution-role-trust-policy.json

   # 附加必要策略
   aws iam attach-role-policy \
     --role-name ecsTaskExecutionRole \
     --policy-arn arn:aws-cn:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

   # 附加访问Secrets Manager的策略
   aws iam attach-role-policy \
     --role-name ecsTaskExecutionRole \
     --policy-arn arn:aws-cn:iam::aws:policy/SecretsManagerReadWrite
   
   # 附加访问SageMaker的策略
   aws iam attach-role-policy \
     --role-name ecsTaskExecutionRole \
     --policy-arn arn:aws-cn:iam::aws:policy/AmazonSageMakerFullAccess
   ```

6. **创建任务定义**

   创建一个名为`task-definition.json`的文件：

   ```json
   {
     "family": "streaming-service",
     "networkMode": "awsvpc",
     "executionRoleArn": "arn:aws-cn:iam::${AWS_ACCOUNT_ID}:role/ecsTaskExecutionRole",
     "taskRoleArn": "arn:aws-cn:iam::${AWS_ACCOUNT_ID}:role/ecsTaskExecutionRole",
     "containerDefinitions": [
       {
         "name": "streaming-container",
         "image": "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/openai-compatible-api:latest",
         "essential": true,
         "portMappings": [
           {
             "containerPort": 8080,
             "hostPort": 8080,
             "protocol": "tcp"
           }
         ],
         "environment": [
           {
             "name": "AWS_REGION",
             "value": "${AWS_REGION}"
           },
           {
             "name": "AUTH_SECRET_ID",
             "value": "${AUTH_SECRET_ID}"
           },
           {
             "name": "API_KEY_CACHE_TTL",
             "value": "${API_KEY_CACHE_TTL}"
           },
           {
             "name": "SAGEMAKER_ENDPOINT_NAME",
             "value": "${MODEL}"
           }
         ],
         "logConfiguration": {
           "logDriver": "awslogs",
           "options": {
             "awslogs-group": "/ecs/streaming-service",
             "awslogs-region": "${AWS_REGION}",
             "awslogs-stream-prefix": "ecs",
             "awslogs-create-group": "true"
           }
         },
         "healthCheck": {
           "command": ["CMD-SHELL", "curl -f http://localhost:8080/health || exit 1"],
           "interval": 30,
           "timeout": 5,
           "retries": 3,
           "startPeriod": 60
         }
       }
     ],
     "requiresCompatibilities": ["FARGATE"],
     "cpu": "1024",
     "memory": "2048"
   }
   ```

   然后注册任务定义：

   ```bash
   # 使用环境变量填充任务定义
   source .env
   envsubst < task-definition.json > task-definition-filled.json
   
   # 注册任务定义
   aws ecs register-task-definition --cli-input-json file://task-definition-filled.json
   ```

7. **创建ECS服务**

   创建一个名为`service-definition.json`的文件：

   ```json
   {
     "cluster": "openai-compatible-api",
     "serviceName": "openai-compatible-api",
     "taskDefinition": "streaming-service",
     "loadBalancers": [
       {
         "targetGroupArn": "<TARGET-GROUP-ARN>",
         "containerName": "streaming-container",
         "containerPort": 8080
       }
     ],
     "desiredCount": 1,
     "launchType": "FARGATE",
     "platformVersion": "LATEST",
     "networkConfiguration": {
       "awsvpcConfiguration": {
         "subnets": ["subnet-05d93b5af94148ba1", "subnet-03442d240c68331e7", "subnet-0eee54d7733f12c28"],
         "securityGroups": ["sg-005ac3befca508cfc"],
         "assignPublicIp": "ENABLED"
       }
     },
     "healthCheckGracePeriodSeconds": 60,
     "schedulingStrategy": "REPLICA",
     "deploymentController": {
       "type": "ECS"
     },
     "deploymentConfiguration": {
       "deploymentCircuitBreaker": {
         "enable": true,
         "rollback": true
       },
       "maximumPercent": 200,
       "minimumHealthyPercent": 100
     }
   }
   ```

   替换`<TARGET-GROUP-ARN>`为之前创建的目标组ARN，然后创建服务：

   ```bash
   aws ecs create-service --cli-input-json file://service-definition.json
   ```

8. **更新现有服务**

   如果需要更新服务（例如部署新版本）：

   ```bash
   aws ecs update-service \
     --cluster openai-compatible-api \
     --service openai-compatible-api \
     --task-definition streaming-service:3 \
     --force-new-deployment
   ```

9. **获取ALB DNS名称**

   获取ALB的DNS名称，用于访问服务：

   ```bash
   aws elbv2 describe-load-balancers \
     --names openai-api-alb \
     --query 'LoadBalancers[0].DNSName' \
     --output text
   ```

   使用获得的DNS名称更新`.env`文件中的`OPENAI_BASE_URL`：

   ```bash
   export OPENAI_BASE_URL="http://<ALB-DNS-NAME>/v1"
   ```

10. **监控服务状态**

    ```bash
    # 检查服务状态
    aws ecs describe-services \
      --cluster openai-compatible-api \
      --services openai-compatible-api
    
    # 查看服务事件
    aws ecs describe-services \
      --cluster openai-compatible-api \
      --services openai-compatible-api \
      --query 'services[0].events'
    
    # 查看运行中的任务
    aws ecs list-tasks \
      --cluster openai-compatible-api \
      --service-name openai-compatible-api
    ```

11. **查看容器日志**

    ```bash
    # 获取任务ID
    TASK_ID=$(aws ecs list-tasks \
      --cluster openai-compatible-api \
      --service-name openai-compatible-api \
      --query 'taskArns[0]' \
      --output text | awk -F'/' '{print $3}')
    
    # 查看日志
    aws logs get-log-events \
      --log-group-name /ecs/streaming-service \
      --log-stream-name ecs/streaming-container/$TASK_ID
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
           - containerPort: 8080
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
               port: 8080
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
       targetPort: 8080
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

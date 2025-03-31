# 使用 Python 3.9 的轻量级基础镜像
FROM public.ecr.aws/docker/library/python:3.9-slim

# 创建非root用户
RUN groupadd -r appuser && useradd -r -g appuser appuser

# 设置工作目录
WORKDIR /app

# 设置AWS区域环境变量
ENV AWS_DEFAULT_REGION=${AWS_REGION}
ENV AWS_REGION=${AWS_REGION}
ENV AUTH_SECRET_ID=${AUTH_SECRET_ID}
ENV API_KEY_CACHE_TTL=${API_KEY_CACHE_TTL}
ENV SAGEMAKER_ENDPOINT_NAME=${SAGEMAKER_ENDPOINT_NAME}

# 先复制requirements.txt
COPY requirements.txt .

# 创建虚拟环境目录并设置权限
RUN pip install --no-cache-dir virtualenv && \
    virtualenv /opt/venv && \
    chown -R appuser:appuser /opt/venv /app

# 切换到非root用户
USER appuser

# 在虚拟环境中安装依赖
RUN . /opt/venv/bin/activate && \
    pip install --no-cache-dir -r requirements.txt

# 复制应用代码并设置权限
USER root
COPY ./app /app/
RUN chown -R appuser:appuser /app

# 切换回非root用户
USER appuser

# 设置环境变量以便python使用虚拟环境
ENV PATH="/opt/venv/bin:$PATH"

# 暴露容器内部端口（Fargate 任务的容器端口）
EXPOSE 8080

# 使用 Gunicorn 部署 Flask 应用，采用 eventlet worker 实现流式响应
CMD ["gunicorn", "--chdir", "/app", "-w", "2", "-k", "eventlet", "-b", "0.0.0.0:8080", "app:app"]


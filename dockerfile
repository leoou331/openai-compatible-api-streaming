# 使用 Python 3.9 的轻量级基础镜像
FROM public.ecr.aws/docker/library/python:3.9-slim

# 设置工作目录
WORKDIR /app

# 设置AWS区域环境变量
ENV AWS_DEFAULT_REGION=cn-northwest-1
ENV AWS_REGION=cn-northwest-1

# 安装依赖
RUN pip install flask boto3 gunicorn eventlet

# 复制应用代码到容器内
COPY app/app.py /app/app.py

# 暴露容器内部端口（Fargate 任务的容器端口）
EXPOSE 8080

# 使用 Gunicorn 部署 Flask 应用，采用 eventlet worker 实现流式响应
CMD ["gunicorn", "--chdir", "/app", "-w", "2", "-k", "eventlet", "-b", "0.0.0.0:8080", "app:app"]


# 国内网络无法直连 Docker Hub 时，构建命令传入镜像源前缀：
#   docker compose build --build-arg BASE_IMG=docker.m.daocloud.io/library/python:3.12-slim
ARG BASE_IMG=python:3.12-slim
FROM ${BASE_IMG}

# 国内网络：apt 换清华源（默认源常被墙）
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g; s|security.debian.org|mirrors.tuna.tsinghua.edu.cn|g' \
        /etc/apt/sources.list.d/debian.sources 2>/dev/null \
    || sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list

# opencv 依赖的系统库 + tzdata
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 tzdata \
    && rm -rf /var/lib/apt/lists/*
ENV TZ=Asia/Shanghai

WORKDIR /app

COPY requirements.txt .
# 国内网络用清华镜像；海外部署可删掉 -i 参数
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

COPY app ./app
COPY prompts ./prompts
COPY static ./static
COPY run.py .

# output / models / prompts 通过 volume 挂载持久化（见 docker-compose.yml）
VOLUME ["/app/output", "/app/models"]

EXPOSE 8300
CMD ["python", "run.py"]

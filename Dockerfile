# ── 阶段 1：构建 ──
# 安装依赖、预下载嵌入模型
FROM python:3.12-slim-bookworm AS builder

WORKDIR /app

# 安装系统构建依赖（部分原生扩展需要编译）
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ && \
    rm -rf /var/lib/apt/lists/*

# 先安装依赖（利用 Docker 层缓存，依赖变更少时跳过重新安装）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 预下载嵌入模型，避免首次启动时等待
# HF_HUB_OFFLINE=1 强制走 ModelScope 路径
ENV HF_HUB_OFFLINE=1
RUN python -c "\
from modelscope import snapshot_download; \
path = snapshot_download('sentence-transformers/all-MiniLM-L6-v2', cache_dir='/app/models'); \
print(f'模型已下载到: {path}')"

# 安装项目本身
COPY pyproject.toml .
COPY src/ src/
COPY tui/ tui/
RUN pip install --no-cache-dir -e .


# ── 阶段 2：运行 ──
# 仅拷贝运行所需文件，不包含构建工具，减小镜像体积
FROM python:3.12-slim-bookworm

WORKDIR /app

# 运行时不需要构建工具，仅保留可能需要的运行时库
RUN apt-get update && \
    apt-get install -y --no-install-recommends libgomp1 && \
    rm -rf /var/lib/apt/lists/*

# 从构建阶段拷贝 Python 包、项目代码和预下载模型
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app/src /app/src
COPY --from=builder /app/tui /app/tui
COPY --from=builder /app/pyproject.toml /app/pyproject.toml
COPY --from=builder /app/models /app/models-image

# Entrypoint script: restores pre-downloaded models when bind mount
# shadows the image-bundled copy on a fresh host.
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# 环境变量
ENV HF_HUB_OFFLINE=1 \
    PYTHONUNBUFFERED=1 \
    EMBEDDING_MODEL_PATH=/app/models/sentence-transformers/all-MiniLM-L6-v2

# 数据目录：文档、向量数据库、模型缓存
# 通过 docker-compose volume 挂载持久化
VOLUME ["/data", "/app/src/chroma_db", "/app/models"]

# 默认入口：先恢复模型，再启动应用
ENTRYPOINT ["/app/docker-entrypoint.sh", "mneme"]

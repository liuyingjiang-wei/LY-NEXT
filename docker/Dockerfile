# docker build -f docker/Dockerfile .   需已包含提交到仓库的 www/（不在此镜像内构建前端）

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    DOCKER_CONTAINER=1 \
    LY_NEXT_PROJECT_ROOT=/app

COPY pyproject.toml uv.lock ./
COPY ly_next ./ly_next
COPY config ./config
COPY www ./www

RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["ly", "--host", "0.0.0.0", "--port", "8000"]

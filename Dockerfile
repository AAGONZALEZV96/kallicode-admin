# syntax=docker/dockerfile:1 
FROM python:3.12-slim-bookworm AS runtime 

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 

WORKDIR /app 
RUN apt-get update && apt-get install -y --no-install-recommends \ 
    ca-certificates \ 
    && rm -rf /var/lib/apt/lists/* 

RUN pip install --no-cache-dir uv 
COPY pyproject.toml ./ 
COPY vendor/ ./vendor/ 
COPY apps/api ./apps/api 
COPY apps/workers ./apps/workers 

RUN uv venv /app/.venv \ 
    && uv pip install --python /app/.venv/bin/python ./vendor/kallicode_core-*.whl \ 
    && uv pip install --python /app/.venv/bin/python \ 
    "fastapi>=0.115,<0.117" "uvicorn[standard]>=0.32,<0.35" \ 
    "pydantic>=2.9,<3" "pydantic-settings>=2.6,<3" \
    "sqlalchemy[asyncio]>=2.0.36,<2.1" "asyncpg>=0.30,<0.31" \
    "redis>=5.2,<6" "pyjwt[crypto]>=2.10,<3" "argon2-cffi>=23.1,<24" \
    "pyotp>=2.9,<3" "qrcode[pil]>=8.0,<9" "httpx>=0.28,<0.29" \
    "azure-storage-blob>=12.24,<13" "azure-identity>=1.19,<2" \
    "email-validator>=2.3.0" 

ENV PATH="/app/.venv/bin:$PATH" \ 
    PYTHONPATH="/app/apps/api/src:/app/apps/workers/src" 

RUN useradd --create-home --uid 10001 appuser 
USER appuser 
EXPOSE 8000 
CMD ["sh", "-c", "uvicorn admin_api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

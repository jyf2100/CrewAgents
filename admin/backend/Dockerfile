# ============================================================================
# Stage 1: Build frontend
# ============================================================================
FROM registry.cn-hangzhou.aliyuncs.com/library/node:20-alpine AS frontend-builder

WORKDIR /app/frontend

# Install dependencies with npmmirror for faster downloads in China
COPY frontend/package.json frontend/package-lock.json ./
RUN npm config set registry https://registry.npmmirror.com && \
    npm ci

# Copy frontend source and build
COPY frontend/ ./
RUN npm run build -- --base /admin/

# ============================================================================
# Stage 2: Runtime with Python
# ============================================================================
FROM registry.cn-hangzhou.aliyuncs.com/library/python:3.11-slim AS runtime

# Install curl for health checks
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies with Tsinghua mirror
COPY backend/requirements.txt ./
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ ./

# Copy built frontend assets from stage 1
COPY --from=frontend-builder /app/frontend/dist /app/static

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 48082

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "48082", "--workers", "1"]

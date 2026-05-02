# ============================================================================
# Stage 1: Build frontend
# ============================================================================
FROM node:20-alpine AS frontend-builder

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
FROM python:3.12-slim AS runtime

# Install curl for health checks and libpq-dev for asyncpg
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies with Tsinghua mirror
COPY backend/requirements.txt ./
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ ./

# Copy swarm package (used by swarm_routes.py)
COPY swarm/ /app/swarm/

# Copy template files (admin/templates/ -> /app/templates/)
COPY templates/ /app/templates/

# Copy built frontend assets from stage 1
COPY --from=frontend-builder /app/frontend/dist /app/static

EXPOSE 48082

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "48082", "--workers", "1"]

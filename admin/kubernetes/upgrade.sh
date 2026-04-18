#!/usr/bin/env bash
# ============================================================================
# Hermes Admin Panel - Upgrade Script
# Build, push, and rollout restart the admin panel
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADMIN_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
NAMESPACE="hermes-agent"
IMAGE="registry.cn-hangzhou.aliyuncs.com/hermes-ops/hermes-admin"

# Allow overriding the tag via env var, default to latest
TAG="${HERMES_ADMIN_TAG:-latest}"
FULL_IMAGE="${IMAGE}:${TAG}"

echo "============================================"
echo "  Hermes Admin Panel - Upgrade"
echo "============================================"

# --------------------------------------------------------------------------
# Step 1: Build the Docker image
# --------------------------------------------------------------------------
echo ""
echo "[Step 1/3] Building Docker image: ${FULL_IMAGE}..."

docker build \
    -t "$FULL_IMAGE" \
    -f "$ADMIN_DIR/backend/Dockerfile" \
    "$ADMIN_DIR"

echo "  Image built successfully."

# --------------------------------------------------------------------------
# Step 2: Push the image to registry
# --------------------------------------------------------------------------
echo ""
echo "[Step 2/3] Pushing image to registry: ${FULL_IMAGE}..."

docker push "$FULL_IMAGE"

echo "  Image pushed successfully."

# --------------------------------------------------------------------------
# Step 3: Rollout restart the deployment
# --------------------------------------------------------------------------
echo ""
echo "[Step 3/3] Triggering rollout restart..."

kubectl rollout restart deployment/hermes-admin -n "$NAMESPACE"

echo "  Waiting for rollout to complete..."
kubectl rollout status deployment/hermes-admin -n "$NAMESPACE" --timeout=180s

echo ""
echo "============================================"
echo "  Upgrade complete!"
echo "  Image: ${FULL_IMAGE}"
echo "============================================"

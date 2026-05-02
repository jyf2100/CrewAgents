#!/usr/bin/env bash
# Deploy hermes-admin to the 184 development cluster
# Usage: ./deploy-admin.sh [image_tag]
set -euo pipefail

TAG="${1:-hermes-admin:latest}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "Building $TAG..."
docker build -f "$PROJECT_DIR/backend/Dockerfile" -t "$TAG" "$PROJECT_DIR/"

echo "Importing to containerd..."
docker save "$TAG" | sudo ctr -n k8s.io images import -

echo "Restarting deployment..."
kubectl -n hermes-agent rollout restart deploy/hermes-admin
kubectl -n hermes-agent rollout status deploy/hermes-admin --timeout=90s

echo "Deploy complete: $TAG"

#!/usr/bin/env bash
# ============================================================================
# Hermes Admin Panel - First Deploy Script
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE="hermes-agent"
IMAGE="registry.cn-hangzhou.aliyuncs.com/hermes-ops/hermes-admin:latest"

echo "============================================"
echo "  Hermes Admin Panel - First Deploy"
echo "============================================"

# --------------------------------------------------------------------------
# Step 1: Create admin secret (generate a random 32-byte hex key)
# --------------------------------------------------------------------------
echo ""
echo "[Step 1/6] Creating admin secret..."
ADMIN_KEY=$(openssl rand -hex 32)

if kubectl get secret hermes-admin-secret -n "$NAMESPACE" > /dev/null 2>&1; then
    echo "  Secret hermes-admin-secret already exists, updating..."
    kubectl delete secret hermes-admin-secret -n "$NAMESPACE"
fi

kubectl create secret generic hermes-admin-secret \
    -n "$NAMESPACE" \
    --from-literal=admin_key="$ADMIN_KEY"

echo "  Admin key generated and stored in secret."
echo "  IMPORTANT: Save this key for authentication: $ADMIN_KEY"
echo ""

# --------------------------------------------------------------------------
# Step 2: Apply RBAC (ServiceAccount, Role, RoleBinding)
# --------------------------------------------------------------------------
echo "[Step 2/6] Applying RBAC resources..."
kubectl apply -f "$SCRIPT_DIR/rbac.yaml"
echo "  RBAC applied."

# --------------------------------------------------------------------------
# Step 3: Apply Deployment
# --------------------------------------------------------------------------
echo ""
echo "[Step 3/6] Applying Deployment..."
kubectl apply -f "$SCRIPT_DIR/deployment.yaml"
echo "  Deployment applied."

# --------------------------------------------------------------------------
# Step 4: Apply Service
# --------------------------------------------------------------------------
echo ""
echo "[Step 4/6] Applying Service..."
kubectl apply -f "$SCRIPT_DIR/service.yaml"
echo "  Service applied."

# --------------------------------------------------------------------------
# Step 5: Patch Ingress to add /admin paths
# --------------------------------------------------------------------------
echo ""
echo "[Step 5/6] Patching Ingress to add /admin paths..."

# Check if the ingress exists
if ! kubectl get ingress hermes-ingress -n "$NAMESPACE" > /dev/null 2>&1; then
    echo "  WARNING: Ingress hermes-ingress not found in namespace $NAMESPACE."
    echo "  Creating a new ingress for admin panel..."

    kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: hermes-ingress
  namespace: hermes-agent
  annotations:
    nginx.ingress.kubernetes.io/use-regex: "true"
spec:
  ingressClassName: nginx
  rules:
    - http:
        paths:
          - path: /admin(/|$)(.*)
            pathType: Prefix
            backend:
              service:
                name: hermes-admin
                port:
                  number: 48082
EOF
    echo "  Ingress created with /admin path."
else
    # Use strategic merge patch to add /admin path
    kubectl patch ingress hermes-ingress -n "$NAMESPACE" --type='strategic' -p '
spec:
  rules:
    - http:
        paths:
          - path: /admin(/|$)(.*)
            pathType: Prefix
            backend:
              service:
                name: hermes-admin
                port:
                  number: 48082
'
    echo "  Ingress patched with /admin path."
fi

# --------------------------------------------------------------------------
# Step 6: Wait for rollout
# --------------------------------------------------------------------------
echo ""
echo "[Step 6/6] Waiting for deployment rollout..."
kubectl rollout status deployment/hermes-admin -n "$NAMESPACE" --timeout=120s

echo ""
echo "============================================"
echo "  Hermes Admin Panel deployed successfully!"
echo "============================================"
echo ""
echo "  Access the admin panel at:"
echo "    http://<ingress-ip>/admin/"
echo ""
echo "  Admin key (save this!): $ADMIN_KEY"
echo ""

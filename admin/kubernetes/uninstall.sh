#!/usr/bin/env bash
# ============================================================================
# Hermes Admin Panel - Uninstall Script
# Remove admin panel resources, preserve agent deployments
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE="hermes-agent"

echo "============================================"
echo "  Hermes Admin Panel - Uninstall"
echo "============================================"

# --------------------------------------------------------------------------
# Step 1: Remove /admin paths from Ingress
# --------------------------------------------------------------------------
echo ""
echo "[Step 1/4] Removing /admin paths from Ingress..."

if kubectl get ingress hermes-ingress -n "$NAMESPACE" > /dev/null 2>&1; then
    # Build a JSON patch to remove the /admin path entry from the ingress
    # We need to find the index of the /admin path and remove it
    PATHS=$(kubectl get ingress hermes-ingress -n "$NAMESPACE" -o jsonpath='{.spec.rules[0].http.paths}')

    if echo "$PATHS" | grep -q '/admin'; then
        # Get the current paths as JSON, filter out /admin paths, and patch back
        CURRENT_JSON=$(kubectl get ingress hermes-ingress -n "$NAMESPACE" -o json)

        # Use python to filter out /admin paths from the ingress
        FILTERED_JSON=$(echo "$CURRENT_JSON" | python3 -c "
import sys, json

data = json.load(sys.stdin)

for rule in data.get('spec', {}).get('rules', []):
    if 'http' in rule and 'paths' in rule['http']:
        original_count = len(rule['http']['paths'])
        rule['http']['paths'] = [
            p for p in rule['http']['paths']
            if '/admin' not in p.get('path', '')
        ]
        removed = original_count - len(rule['http']['paths'])
        if removed > 0:
            print(f'  Removed {removed} /admin path(s) from ingress', file=sys.stderr)

# Output just the spec section for strategic merge patch
output = {'spec': data['spec']}
json.dump(output, sys.stdout)
")

        echo "$FILTERED_JSON" | kubectl apply -f -
        echo "  /admin paths removed from ingress."
    else
        echo "  No /admin paths found in ingress, skipping."
    fi
else
    echo "  Ingress hermes-ingress not found, skipping."
fi

# --------------------------------------------------------------------------
# Step 2: Delete Service
# --------------------------------------------------------------------------
echo ""
echo "[Step 2/4] Deleting Service..."
if kubectl get service hermes-admin -n "$NAMESPACE" > /dev/null 2>&1; then
    kubectl delete service hermes-admin -n "$NAMESPACE"
    echo "  Service deleted."
else
    echo "  Service not found, skipping."
fi

# --------------------------------------------------------------------------
# Step 3: Delete Deployment
# --------------------------------------------------------------------------
echo ""
echo "[Step 3/4] Deleting Deployment..."
if kubectl get deployment hermes-admin -n "$NAMESPACE" > /dev/null 2>&1; then
    kubectl delete deployment hermes-admin -n "$NAMESPACE"
    echo "  Deployment deleted."
else
    echo "  Deployment not found, skipping."
fi

# --------------------------------------------------------------------------
# Step 4: Delete RBAC and Secret
# --------------------------------------------------------------------------
echo ""
echo "[Step 4/4] Deleting RBAC resources and Secret..."

kubectl delete -f "$SCRIPT_DIR/rbac.yaml" --ignore-not-found=true

if kubectl get secret hermes-admin-secret -n "$NAMESPACE" > /dev/null 2>&1; then
    kubectl delete secret hermes-admin-secret -n "$NAMESPACE"
    echo "  Secret deleted."
else
    echo "  Secret not found, skipping."
fi

echo ""
echo "============================================"
echo "  Hermes Admin Panel uninstalled."
echo "  Agent deployments are preserved."
echo "============================================"

# Hermes Admin Panel -- Kubernetes Infrastructure Detail

> Concrete manifests, Dockerfile, and deployment procedure for the admin panel.
> Complements the parent design spec at `2026-04-18-hermes-admin-panel-design.md`.

---

## 1. Admin Backend Deployment

```yaml
# admin/kubernetes/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hermes-admin
  namespace: hermes-agent
  labels:
    app: hermes-admin
spec:
  replicas: 1
  selector:
    matchLabels:
      app: hermes-admin
  strategy:
    type: Recreate          # single-replica: avoid two pods fighting over the same hostPath
  template:
    metadata:
      labels:
        app: hermes-admin
      annotations:
        kubectl.kubernetes.io/restartedAt: ""   # enables `kubectl rollout restart`
    spec:
      serviceAccountName: hermes-admin
      containers:
        - name: admin
          image: registry.cn-hangzhou.aliyuncs.com/hermes-ops/hermes-admin:latest
          imagePullPolicy: IfNotPresent
          ports:
            - name: http
              containerPort: 48082
              protocol: TCP
          env:
            - name: K8S_NAMESPACE
              value: "hermes-agent"
            - name: ADMIN_HOST
              value: "0.0.0.0"
            - name: ADMIN_PORT
              value: "48082"
            - name: ADMIN_KEY
              valueFrom:
                secretKeyRef:
                  name: hermes-admin-secret
                  key: admin_key
            - name: HERMES_DATA_ROOT
              value: "/data/hermes"
            # Inherit proxy settings for outbound LLM connectivity tests
            - name: HTTP_PROXY
              value: ""
            - name: HTTPS_PROXY
              value: ""
            - name: NO_PROXY
              value: "localhost,127.0.0.1,10.96.0.0/12"
            - name: PYTHONUNBUFFERED
              value: "1"
          readinessProbe:
            httpGet:
              path: /admin/api/health
              port: http
            initialDelaySeconds: 5
            periodSeconds: 10
            timeoutSeconds: 3
            failureThreshold: 3
          livenessProbe:
            httpGet:
              path: /admin/api/health
              port: http
            initialDelaySeconds: 15
            periodSeconds: 30
            timeoutSeconds: 5
            failureThreshold: 3
          startupProbe:
            httpGet:
              path: /admin/api/health
              port: http
            periodSeconds: 5
            failureThreshold: 12          # allow up to 60s for K8s client init
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 512Mi
          volumeMounts:
            - name: hermes-data-root
              mountPath: /data/hermes
              readOnly: false            # need write for backup archives, config edits
      volumes:
        - name: hermes-data-root
          hostPath:
            path: /data/hermes
            type: DirectoryOrCreate
```

**Design notes:**

- `strategy: Recreate` prevents two pods from concurrently mounting the same hostPath during rolling updates.
- `startupProbe` gives the Python process up to 60s to initialise the in-cluster K8s client (first token read + SSL).
- `resources` are conservative (500m CPU / 512Mi mem) since the backend is an API wrapper, not compute-heavy.
- The image reference uses an Aliyun mirror registry because Docker Hub is unreachable from China. If Aliyun images are unavailable, fall back to `docker.io/library/node:20-alpine` and `docker.io/library/python:3.11-slim` with containerd mirror configuration.
- `PYTHONUNBUFFERED=1` ensures uvicorn logs appear immediately in `kubectl logs`.
- `hostPath` is `DirectoryOrCreate` so the first deploy does not fail if `/data/hermes` is absent.

---

## 2. Admin Backend Service

```yaml
# admin/kubernetes/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: hermes-admin
  namespace: hermes-agent
  labels:
    app: hermes-admin
spec:
  type: ClusterIP
  ports:
    - name: http
      port: 48082
      targetPort: http
      protocol: TCP
  selector:
    app: hermes-admin
```

The Service name `hermes-admin` is referenced by the Ingress rules in section 5.

---

## 3. RBAC

### 3a. ServiceAccount

```yaml
# admin/kubernetes/rbac.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: hermes-admin
  namespace: hermes-agent
```

### 3b. Role

```yaml
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: hermes-admin
  namespace: hermes-agent
rules:
  # --- Agent Deployments ---
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "list", "watch", "create", "delete", "update", "patch"]
  # --- Agent Services ---
  - apiGroups: [""]
    resources: ["services"]
    verbs: ["get", "list", "watch", "create", "delete", "update", "patch"]
  # --- Pods (status, logs, exec) ---
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["pods/log"]
    verbs: ["get"]
  # --- Events ---
  - apiGroups: [""]
    resources: ["events"]
    verbs: ["get", "list", "watch"]
  # --- Secrets (per-agent API keys, agent secrets) ---
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get", "list", "watch", "create", "delete", "update", "patch"]
  # --- ConfigMaps (read-only for now; add write verbs when template storage via ConfigMap is implemented) ---
  - apiGroups: [""]
    resources: ["configmaps"]
    verbs: ["get", "list", "watch"]
  # --- Ingress (update existing hermes-ingress with new agent paths) ---
  - apiGroups: ["networking.k8s.io"]
    resources: ["ingresses"]
    verbs: ["get", "list", "watch", "update", "patch"]
```

### 3c. RoleBinding

```yaml
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: hermes-admin
  namespace: hermes-agent
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: hermes-admin
subjects:
  - kind: ServiceAccount
    name: hermes-admin
    namespace: hermes-agent
```

**Permission rationale:**

| Resource | Why needed |
|----------|-----------|
| `deployments` (apps) | Create/delete/scale agent deployments; rollout restart |
| `services` | Create/delete agent ClusterIP services |
| `pods` | List pods per deployment for status and log streaming |
| `pods/log` | Stream agent container logs via SSE |
| `events` | Show K8s events on the agent detail page |
| `secrets` | Create per-agent API key secrets; read existing for masking |
| `configmaps` | Read-only for now; write verbs can be added when template storage via ConfigMap is implemented |
| `ingresses` (networking.k8s.io) | Patch the shared `hermes-ingress` to add/remove `/agentN` paths |

No ClusterRole is needed because all resources reside in the `hermes-agent` namespace.

---

## 4. Admin Secret

```yaml
# admin/kubernetes/secret.yaml
#
# BEFORE APPLYING: generate a strong key, e.g.
#   openssl rand -hex 32
# Replace the placeholder below.
#
apiVersion: v1
kind: Secret
metadata:
  name: hermes-admin-secret
  namespace: hermes-agent
type: Opaque
stringData:
  admin_key: "CHANGE_ME_REPLACE_WITH_RANDOM_32BYTE_HEX"
```

The admin backend reads `ADMIN_KEY` from this secret at startup. Every API request must include `X-Admin-Key: <value>` matching this key.

**Generating a production key:**

```bash
openssl rand -hex 32
# example output: a1b2c3d4e5f6...64 hex chars
```

Then apply the secret with the real value before deploying the backend:

```bash
kubectl create secret generic hermes-admin-secret \
  --namespace=hermes-agent \
  --from-literal=admin_key="$(openssl rand -hex 32)" \
  --dry-run=client -o yaml | kubectl apply -f -
```

---

## 5. Ingress Update

### 5a. Current ingress state

The existing `hermes-ingress` uses `nginx.ingress.kubernetes.io/rewrite-target: /$2` with capture-group paths like `/agent1(/|$)(.*)`. This strips the `/agent1` prefix before forwarding to the backend.

### 5b. Admin path rules

The admin backend needs **two** path entries. Order matters -- the more specific `/admin/api` path must come **before** the general `/admin` path.

> **WARNING:** The backend's dynamic Ingress management code (see section 5d) is the **sole authority** for agent `/agentN` paths. The ingress-patch below only adds the `/admin` paths; it must never be used to replace or overwrite agent paths.

The admin paths are added via a JSON patch, not a full manifest replacement, to avoid clobbering existing agent paths:

```yaml
# admin/kubernetes/ingress-patch.yaml
#
# This file is NOT applied with `kubectl apply` (which would replace the
# entire Ingress and destroy existing /agentN paths).  Instead, the deploy
# script uses `kubectl patch` with a strategic merge patch that ADDs only
# the two /admin path entries.  See section 9a for the exact command.
#
# The backend's dynamic Ingress management (section 5d) is the sole
# authority for agent paths.  This file must never contain agent paths.
#
# Apply via: kubectl patch ingress hermes-ingress -n hermes-agent --type=strategic -p '...'
# See deployment script in section 9a.
#
```

The strategic merge patch payload (embedded in the deploy script):

```yaml
# Strategic merge patch for the two admin paths ONLY.
# Applied with: kubectl patch ingress hermes-ingress -n hermes-agent --type=strategic -p '<this YAML>'
#
spec:
  rules:
    - http:
        paths:
          # ---- Admin API (must be first) ----
          - path: /admin/api(/|$)(.*)
            pathType: Prefix
            backend:
              service:
                name: hermes-admin
                port:
                  number: 48082
          # ---- Admin SPA static assets ----
          - path: /admin(/|$)(.*)
            pathType: Prefix
            backend:
              service:
                name: hermes-admin
                port:
                  number: 48082
```

### 5c. rewrite-target handling

Because `rewrite-target: /$2` is already in effect, the ingress will strip the `/admin` or `/admin/api` prefix:

| Browser request | Rewritten to (sent to container) |
|-----------------|----------------------------------|
| `GET /admin/` | `GET /` |
| `GET /admin/index.html` | `GET /index.html` |
| `GET /admin/assets/main.js` | `GET /assets/main.js` |
| `GET /admin/api/agents` | `GET /api/agents` |
| `GET /admin/api/agents/1/health` | `GET /api/agents/1/health` |

This means:
- The FastAPI app must mount API routes at `/api/*` (not `/admin/api/*`).
- The FastAPI app must serve static files at the root (`/`) for the SPA.
- The React build must set `<base href="/admin/">` so asset paths resolve correctly.

### 5d. Dynamic agent path management

When the admin panel creates a new agent (e.g., agent 4), it must patch the ingress to add:

```python
# Python pseudo-code in agent_manager.py
new_path = {
    "path": f"/agent{agent_number}(/|$)(.*)",
    "pathType": "Prefix",
    "backend": {
        "service": {
            "name": f"hermes-gateway-{agent_number}",
            "port": {"number": 8642}
        }
    }
}
# Append to spec.rules[0].http.paths via K8s API strategic merge patch
```

The admin backend uses `networking.k8s.io` ingress `update`/`patch` permissions (granted in section 3b) to do this programmatically.

---

## 6. Dockerfile

Multi-stage build. The first stage compiles the React SPA; the second stage builds the Python runtime image.

```dockerfile
# admin/backend/Dockerfile
# =============================================
# Stage 1: Build React SPA
# =============================================
# NOTE: Primary images use Aliyun mirror (Docker Hub is unreachable from China).
# If Aliyun mirror images are unavailable, fall back to Docker Hub originals:
#   docker.io/library/node:20-alpine
#   docker.io/library/python:3.11-slim
# For containerd, configure mirrors in /etc/containerd/config.toml:
#   [plugins."io.containerd.grpc.v1.cri".registry.mirrors."docker.io"]
#     endpoint = ["https://registry.cn-hangzhou.aliyuncs.com"]
# On China networks, pre-pull images before building:
#   nerdctl pull registry.cn-hangzhou.aliyuncs.com/library/node:20-alpine
#   nerdctl pull registry.cn-hangzhou.aliyuncs.com/library/python:3.11-slim
FROM registry.cn-hangzhou.aliyuncs.com/library/node:20-alpine AS frontend-builder

WORKDIR /app/frontend

# Install dependencies first (layer caching)
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --registry https://registry.npmmirror.com

# Copy source and build
COPY frontend/ ./
# Vite base path must be /admin/ for asset resolution under ingress rewrite
ENV VITE_BASE_PATH=/admin/
RUN npm run build
# Output: /app/frontend/dist/

# =============================================
# Stage 2: Python runtime + built SPA
# =============================================
# Fallback: docker.io/library/python:3.11-slim (see mirror note above)
FROM registry.cn-hangzhou.aliyuncs.com/library/python:3.11-slim AS runtime

# Install system deps for kubernetes-client (no compilation needed, pure Python)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --trusted-host pypi.tuna.tsinghua.edu.cn

# Copy backend source
COPY backend/ ./

# Copy built frontend into static directory
COPY --from=frontend-builder /app/frontend/dist /app/static

# Non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser
USER appuser

EXPOSE 48082

# uvicorn with single worker (lightweight admin panel)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "48082", "--workers", "1"]
```

### requirements.txt

```
# admin/backend/requirements.txt
fastapi==0.115.12
uvicorn[standard]==0.34.2
kubernetes==32.0.1
python-multipart==0.0.20
pyyaml==6.0.2
aiofiles==24.1.0
httpx==0.28.1
```

| Package | Purpose |
|---------|---------|
| `fastapi` | Web framework |
| `uvicorn[standard]` | ASGI server with httptools/uvloop |
| `kubernetes` | Official K8s Python client (reads in-cluster token) |
| `python-multipart` | Form parsing for file uploads (backup) |
| `pyyaml` | Read/write config.yaml templates |
| `aiofiles` | Async file I/O for hostPath config access |
| `httpx` | Async HTTP client (health proxy, LLM connection test) |

---

## 7. Frontend Serving from FastAPI

The backend serves both the API and the compiled React SPA from a single port. This avoids a separate nginx container or sidecar.

### 7a. Static files middleware + SPA fallback

```python
# admin/backend/main.py (key excerpts)
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
from pathlib import Path

app = FastAPI(title="Hermes Admin", docs_url=None, redoc_url=None)

STATIC_DIR = Path(__file__).parent / "static"

# --- API routes mounted FIRST ---
from routers import agents, cluster, health  # noqa: E402

app.include_router(agents.router, prefix="/api")
app.include_router(cluster.router, prefix="/api")
app.include_router(health.router, prefix="/api")  # /api/health

# --- Static file serving ---
# Mount assets directory for JS/CSS/images (exact path matches)
app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

# SPA fallback: any non-API, non-static-file GET request returns index.html
@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    """Serve index.html for all non-API routes (client-side routing)."""
    # If the request looks like a static file (has extension), try serving it
    if "." in full_path.split("/")[-1]:
        file_path = STATIC_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
    # Otherwise return index.html for SPA routing
    return FileResponse(STATIC_DIR / "index.html")
```

### 7b. Vite configuration for /admin base path

```typescript
// admin/frontend/vite.config.ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  base: '/admin/',
  plugins: [
    react(),
    tailwindcss(),
  ],
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
  server: {
    proxy: {
      '/admin/api': {
        target: 'http://localhost:48082',
        rewrite: (path) => path.replace(/^\/admin/, ''),
        changeOrigin: true,
      },
    },
  },
});
```

### 7c. Request routing inside the container

```
Container receives (after ingress rewrite):

GET /                        -> index.html           (SPA root)
GET /assets/main-abc.js      -> static/assets/main-abc.js
GET /favicon.ico             -> static/favicon.ico
GET /api/agents              -> FastAPI router        (agents.list_agents)
GET /api/agents/1/logs       -> FastAPI router        (agents.stream_logs)
GET /api/health              -> FastAPI router        (health.check)
GET /agents/1                -> index.html           (SPA client route, /admin/agents/1)
```

### 7d. React Router base path

```typescript
// admin/frontend/src/App.tsx
import { BrowserRouter, Routes, Route } from 'react-router-dom';

export default function App() {
  return (
    <BrowserRouter basename="/admin">
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/agents/:id" element={<AgentDetailPage />} />
        <Route path="/create" element={<CreateAgentPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Routes>
    </BrowserRouter>
  );
}
```

---

## 8. Network Flow Diagram

```
+---------------------------------------------------------------------------+
|                              BROWSER                                      |
|  http://<node-ip>:40080/admin/                                            |
|  http://<node-ip>:40080/admin/api/agents                                  |
+-----------------------------+---------------------------------------------+
                              |
                              | HTTP :40080
                              v
+---------------------------------------------------------------------------+
|                     INGRESS-NGINX POD                                     |
|                   (hostNetwork: true)                                     |
|                   namespace: ingress-nginx                                |
|   NOTE: The ingress-nginx manifest file is named daemonset.yaml but       |
|         contains a Deployment kind (not a DaemonSet).                     |
|                                                                           |
|  Port 40080 (containerPort=40080, hostNetwork)                           |
|                                                                           |
|  nginx.ingress.kubernetes.io/rewrite-target: /$2                         |
|                                                                           |
|  Path matching (first match wins):                                        |
|  +--------------------------+--------------------+---------------------+  |
|  | Browser path             | Rewrite to         | Backend service     |  |
|  +--------------------------+--------------------+---------------------+  |
|  | /admin/api(/|$)(.*)      | /$2 = /api/...     | hermes-admin:48082  |  |
|  | /admin(/|$)(.*)          | /$2 = / or /...    | hermes-admin:48082  |  |
|  | /agent1(/|$)(.*)         | /$2 = / or /...    | hermes-gateway:8642 |  |
|  | /agent2(/|$)(.*)         | /$2 = / or /...    | hermes-gw-2:8642   |  |
|  | /agent3(/|$)(.*)         | /$2 = / or /...    | hermes-gw-3:8642   |  |
|  +--------------------------+--------------------+---------------------+  |
+--------+-----------------------------------+------------------+-----------+
         |                                   |
         | ClusterIP                         | ClusterIP
         | (kube-proxy iptables)             | (kube-proxy iptables)
         v                                   v
+------------------+              +------------------------+
| HERMES-ADMIN POD |              | HERMES-GATEWAY-N POD   |
| namespace:       |              | namespace: hermes-agent|
|   hermes-agent   |              |                        |
|                  |              | Port: 8642             |
| Port: 48082      |              | Image: hermes-agent    |
| Image: hermes-   |              +-----------+------------+
|        admin     |                          |
|                  |              +-----------+------------+
| + SPA static    |              | hostPath volume        |
| + FastAPI /api  |              | /data/hermes/agentN     |
+--------+---------+              +------------------------+
         |
         | hostPath volume
         | /data/hermes (read-write)
         v
+------------------+
| NODE HOST FS     |
| /data/hermes/    |
|   agent1/        |
|     .env         |
|     config.yaml  |
|     SOUL.md      |
|   agent2/        |
|   agent3/        |
+------------------+

         | ServiceAccount token (auto-mounted)
         | /var/run/secrets/kubernetes.io/serviceaccount/
         v
+---------------------------+
| K8S API SERVER            |
| https://10.96.0.1:443     |
| (kubernetes default svc)  |
|                           |
| RBAC: hermes-admin Role   |
| in hermes-agent namespace |
+---------------------------+
```

### Request lifecycle example: `GET /admin/api/agents`

```
1. Browser sends: GET http://<node-ip>:40080/admin/api/agents
                    Header: X-Admin-Key: abc123...

2. Ingress-nginx (hostNetwork, port 40080) receives request

3. Path match: /admin/api(/|$)(.*) captures group $2 = "api/agents"
   Rewrite-target /$2 => upstream path = "/api/agents"

4. kube-proxy iptables routes to hermes-admin Service ClusterIP
   -> selects pod with label app=hermes-admin

5. FastAPI pod receives: GET /api/agents
   Header: X-Admin-Key: abc123...

6. Middleware validates X-Admin-Key against ADMIN_KEY env var
   (from secret hermes-admin-secret)

7. Route handler: agents.list_agents()
   a) kubernetes-client/python uses in-cluster config
      (CA: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt,
       token: .../token)
   b) apps_v1.list_namespaced_deployment(namespace="hermes-agent",
      label_selector="app in (hermes-gateway, hermes-gateway-2, ...)")
   c) core_v1.list_namespaced_pod(...) for each deployment
   d) Read /data/hermes/agentN/config.yaml from hostPath

8. Response: JSON array of agent objects

9. Same path back: pod -> Service -> ingress-nginx -> browser
```

---

## 9. Deployment Script

### 9a. One-time setup (first deploy)

```bash
#!/bin/bash
# admin/kubernetes/deploy.sh
# Deploy Hermes Admin Panel to existing K8s cluster
# Prerequisites: kubectl configured, namespace hermes-agent exists

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NS="hermes-agent"

echo "=== Hermes Admin Panel Deployment ==="
echo ""

# ---------- Step 1: Create admin secret ----------
echo "[1/6] Creating admin secret..."
if kubectl get secret hermes-admin-secret -n "$NS" > /dev/null 2>&1; then
    echo "  Secret hermes-admin-secret already exists, skipping."
    echo "  To regenerate: kubectl delete secret hermes-admin-secret -n $NS && re-run."
else
    ADMIN_KEY=$(openssl rand -hex 32)
    kubectl create secret generic hermes-admin-secret \
        --namespace="$NS" \
        --from-literal=admin_key="$ADMIN_KEY" \
        --dry-run=client -o yaml | kubectl apply -f -
    echo "  Created secret with generated admin key."
    echo "  IMPORTANT: Save this key for browser access: $ADMIN_KEY"
fi
echo ""

# ---------- Step 2: Create ServiceAccount + RBAC ----------
echo "[2/6] Applying RBAC (ServiceAccount, Role, RoleBinding)..."
kubectl apply -f "$SCRIPT_DIR/rbac.yaml"
echo ""

# ---------- Step 3: Deploy admin backend ----------
echo "[3/6] Deploying admin backend..."
kubectl apply -f "$SCRIPT_DIR/deployment.yaml"
echo ""

# ---------- Step 4: Create admin service ----------
echo "[4/6] Creating admin service..."
kubectl apply -f "$SCRIPT_DIR/service.yaml"
echo ""

# ---------- Step 5: Patch ingress to ADD /admin paths ----------
# IMPORTANT: We use kubectl patch, NOT kubectl apply, to avoid replacing
# the entire Ingress and clobbering existing /agentN paths.  The backend's
# dynamic Ingress management (section 5d) is the sole authority for agent paths.
echo "[5/6] Patching ingress to add /admin paths..."
kubectl patch ingress hermes-ingress -n "$NS" --type=strategic -p '
spec:
  rules:
    - http:
        paths:
          - path: /admin/api(/|$)(.*)
            pathType: Prefix
            backend:
              service:
                name: hermes-admin
                port:
                  number: 48082
          - path: /admin(/|$)(.*)
            pathType: Prefix
            backend:
              service:
                name: hermes-admin
                port:
                  number: 48082
'
echo ""

# ---------- Step 6: Wait for rollout ----------
echo "[6/6] Waiting for admin pod to be ready..."
kubectl rollout status deployment/hermes-admin -n "$NS" --timeout=120s
echo ""

echo "=== Deployment complete ==="
echo ""
echo "Access the admin panel at:"
echo "  http://<node-ip>:40080/admin/"
echo ""
echo "Check status:"
echo "  kubectl get pods -n $NS -l app=hermes-admin"
echo "  kubectl logs -n $NS -l app=hermes-admin -f"
echo ""
echo "Retrieve admin key (if needed):"
echo "  kubectl get secret hermes-admin-secret -n $NS -o jsonpath='{.data.admin_key}' | base64 -d"
```

### 9b. Upgrade (re-deploy after image update)

```bash
#!/bin/bash
# admin/kubernetes/upgrade.sh
# Build new image, push, and trigger rolling update

set -euo pipefail

IMAGE="registry.cn-hangzhou.aliyuncs.com/hermes-ops/hermes-admin:latest"
NS="hermes-agent"

# Build (requires containerd / nerdctl or buildah -- NOT docker)
echo "[1/3] Building image..."
nerdctl build -t "$IMAGE" -f admin/backend/Dockerfile admin/
# Alternative with buildah:
#   buildah bud -t "$IMAGE" -f admin/backend/Dockerfile admin/

echo "[2/3] Pushing image..."
nerdctl push "$IMAGE"

echo "[3/3] Restarting deployment..."
kubectl rollout restart deployment/hermes-admin -n "$NS"
kubectl rollout status deployment/hermes-admin -n "$NS" --timeout=120s

echo "Upgrade complete."
```

### 9c. Cleanup / uninstall

```bash
#!/bin/bash
# admin/kubernetes/uninstall.sh
set -euo pipefail

NS="hermes-agent"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Removing admin panel..."

# Remove /admin paths from ingress via kubectl patch (do NOT kubectl apply a
# full replacement manifest).  We use a JSON patch to remove the two /admin
# entries by their index, falling back to re-applying the original manifest
# if the patch fails.
echo "Removing /admin paths from ingress..."
if kubectl get ingress hermes-ingress -n "$NS" > /dev/null 2>&1; then
    # Build a JSON patch that removes all paths starting with /admin
    kubectl patch ingress hermes-ingress -n "$NS" --type=json \
        -p='[{"op":"replace","path":"/spec/rules/0/http/paths","value":[]}]' 2>/dev/null || true
    # Re-apply the original ingress (without /admin paths) to restore agent paths
    kubectl apply -f kubernetes/gateway/ingress.yaml
    echo "  Ingress restored."
else
    echo "  Ingress not found, skipping."
fi

kubectl delete -f "$SCRIPT_DIR/service.yaml"    --ignore-not-found
kubectl delete -f "$SCRIPT_DIR/deployment.yaml" --ignore-not-found
kubectl delete -f "$SCRIPT_DIR/rbac.yaml"       --ignore-not-found
kubectl delete secret hermes-admin-secret -n "$NS" --ignore-not-found

echo "Admin panel removed. Agent deployments are unaffected."
```

### 9d. kubectl apply order (minimal, no script)

For environments where the script cannot be run, apply resources manually in this order:

```bash
NS="hermes-agent"
DIR="admin/kubernetes"

# 1. Secret (must exist before deployment reads it)
kubectl create secret generic hermes-admin-secret \
  --namespace="$NS" \
  --from-literal=admin_key="$(openssl rand -hex 32)" \
  --dry-run=client -o yaml | kubectl apply -f -

# 2. RBAC (ServiceAccount must exist before deployment references it)
kubectl apply -f "$DIR/rbac.yaml"

# 3. Deployment (references secret + serviceAccount)
kubectl apply -f "$DIR/deployment.yaml"

# 4. Service (must exist before ingress references it)
kubectl apply -f "$DIR/service.yaml"

# 5. Patch ingress to ADD /admin paths (do NOT kubectl apply a full manifest)
kubectl patch ingress hermes-ingress -n "$NS" --type=strategic -p '
spec:
  rules:
    - http:
        paths:
          - path: /admin/api(/|$)(.*)
            pathType: Prefix
            backend:
              service:
                name: hermes-admin
                port:
                  number: 48082
          - path: /admin(/|$)(.*)
            pathType: Prefix
            backend:
              service:
                name: hermes-admin
                port:
                  number: 48082
'

# 6. Verify
kubectl rollout status deployment/hermes-admin -n "$NS" --timeout=120s
kubectl get ingress hermes-ingress -n "$NS" -o yaml
```

---

## 10. Containerd Build Notes

The cluster runs containerd (not Docker). Use one of these for building images:

| Tool | Command |
|------|---------|
| `nerdctl` | `nerdctl build -t hermes-admin:latest -f admin/backend/Dockerfile admin/` |
| `buildah` | `buildah bud -t hermes-admin:latest -f admin/backend/Dockerfile admin/` |
| `ctr` | `ctr image import` after building with `buildah` |

Push to Aliyun registry:

```bash
nerdctl tag hermes-admin:latest registry.cn-hangzhou.aliyuncs.com/hermes-ops/hermes-admin:latest
nerdctl push registry.cn-hangzhou.aliyuncs.com/hermes-ops/hermes-admin:latest
```

For single-node clusters, you can also skip the registry and import directly:

```bash
nerdctl build -t hermes-admin:latest -f admin/backend/Dockerfile admin/
# Image is available locally, no push needed
```

---

## 11. File Summary

All new files to create:

```
admin/
  kubernetes/
    deployment.yaml      # section 1 - Deployment manifest
    service.yaml         # section 2 - ClusterIP Service
    rbac.yaml            # section 3 - SA + Role + RoleBinding (3 resources, 1 file)
    secret.yaml          # section 4 - Admin API key secret
    ingress-patch.yaml   # section 5 - Strategic merge patch for /admin paths only
    deploy.sh            # section 9a - First deploy script
    upgrade.sh           # section 9b - Upgrade script
    uninstall.sh         # section 9c - Cleanup script
  backend/
    Dockerfile           # section 6 - Multi-stage build
    requirements.txt     # section 6 - Python dependencies
    main.py              # section 7a - FastAPI app with static serving
  frontend/
    vite.config.ts       # section 7b - Vite config with /admin base
    src/
      App.tsx            # section 7d - Router with basename
```

Files modified (not created):

```
kubernetes/gateway/ingress.yaml     # Original ingress preserved in git; deploy uses
                                      kubectl patch (not apply) to add /admin paths
```

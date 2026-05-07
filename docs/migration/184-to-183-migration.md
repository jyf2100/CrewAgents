# 184→183 集群迁移操作手册

> 将 184 开发集群版本部署到 183 测试集群。所有命令可直接复制执行。

## 前置条件

- 184: 本机可直接 `kubectl` 操作
- 183: 通过 `ssh root@172.32.153.183` 操作，ctr 路径 `/opt/containerd/bin/ctr`
- 两边 namespace 均为 `hermes-agent`

**安全前置（在 183 上首先执行）:**
```bash
export HISTFILE=/dev/null   # 防止密钥进入 bash 历史记录
```

## 环境差异摘要

| 项目 | 184 (开发) | 183 (测试) | 迁移动作 |
|------|-----------|-----------|---------|
| Admin 镜像 | 本地构建最新版 | 旧版 | 传输+升级 |
| Orchestrator | 有 | 无 | 新增 |
| Redis 密码 | 有 | 无 | 升级 |
| DB 名 | hermes_admin | hermes_admin | 已统一 |
| DB 密码 | hermes_pg_2024 | hermes2024 | 保持 183 的 |
| Ingress /admin/assets/ | 有 | 无 | 添加 |
| WebUI Ingress | 有 | 无 | 添加 |
| Admin SVC 类型 | ClusterIP | NodePort | 改为 ClusterIP |
| Gateway 1-13 | 3 个 | 13 个 | **不动（允许重启）** |

## Step 1: 传输镜像 (184→183)

```bash
# === 在 184 上执行 ===
docker save hermes-admin:latest | gzip > /tmp/hermes-admin.tar.gz
docker save hermes-orchestrator:latest | gzip > /tmp/hermes-orchestrator.tar.gz
scp /tmp/hermes-admin.tar.gz /tmp/hermes-orchestrator.tar.gz root@172.32.153.183:/tmp/
```

```bash
# === 在 183 上执行 ===
gunzip -c /tmp/hermes-admin.tar.gz | /opt/containerd/bin/ctr -n k8s.io images import -
gunzip -c /tmp/hermes-orchestrator.tar.gz | /opt/containerd/bin/ctr -n k8s.io images import -
```

**验证:**
```bash
# 183 上
/opt/containerd/bin/ctr -n k8s.io images ls | grep -E "hermes-admin|hermes-orchestrator"
```

## Step 1.5: 前置验证

```bash
# === 在 183 上执行 ===

# 1. 检查 Redis PVC 是否存在
kubectl get pvc hermes-redis-pvc -n hermes-agent 2>/dev/null && echo "REDIS_PVC=exists" || echo "REDIS_PVC=NOT_FOUND"

# 2. 检查 Ingress Controller NodePort
kubectl get svc -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}{"\t"}{.spec.type}{"\t"}{.spec.ports[0].nodePort}{"\n"}{end}' | grep -i ingress
# 记录 NodePort 端口号，后续步骤中的 40080 可能需要替换为实际端口

# 3. 检查当前 Redis 是否有密码
kubectl exec -n hermes-agent deploy/hermes-redis -- redis-cli ping 2>/dev/null
# PONG = 无密码; NOAUTH = 有密码

# 4. 验证 hermes-db-secret 包含 api_key（Orchestrator 需要引用）
kubectl get secret hermes-db-secret -n hermes-agent -o jsonpath='{.data.api_key}' 2>/dev/null && echo "API_KEY=exists" || echo "API_KEY=NOT_FOUND"
# 如果 NOT_FOUND，需要先添加: kubectl patch secret hermes-db-secret -n hermes-agent -p '{"data":{"api_key":"'$(echo -n "your-key" | base64)'"}}'

# 5. 检查 Ingress 现有路径（确认 /admin/api 和 /admin 已存在）
kubectl get ingress hermes-ingress -n hermes-agent -o jsonpath='{.spec.rules[0].http.paths[*].path}' | tr ' ' '\n'
```

## Step 2: 创建 K8s Secrets

```bash
# === 在 183 上执行 ===

# Redis 密码（生成随机密码）
REDIS_PASS=$(openssl rand -hex 16)
kubectl create secret generic hermes-redis-secret \
  --from-literal=redis-password="$REDIS_PASS" \
  --from-literal=redis-url="redis://:${REDIS_PASS}@hermes-redis:6379/0" \
  -n hermes-agent

# Orchestrator API Key
kubectl create secret generic hermes-orchestrator-secret \
  --from-literal=ORCHESTRATOR_API_KEY=$(openssl rand -hex 32) \
  -n hermes-agent

# Admin Internal Token（Orchestrator 需要在 Admin 启动前引用此 secret）
kubectl create secret generic hermes-admin-internal-secret \
  --from-literal=admin_internal_token=$(openssl rand -hex 32) \
  -n hermes-agent

# DATABASE_URL — 从现有 hermes-db-secret 中读取凭据构建
DB_USER=$(kubectl get secret hermes-db-secret -n hermes-agent -o jsonpath='{.data.username}' | base64 -d)
DB_PASS=$(kubectl get secret hermes-db-secret -n hermes-agent -o jsonpath='{.data.password}' | base64 -d)
kubectl create secret generic hermes-database-secret \
  --from-literal=database-url="postgresql+asyncpg://${DB_USER}:${DB_PASS}@postgres:5432/hermes_admin" \
  -n hermes-agent

# 清除临时变量
unset DB_USER DB_PASS REDIS_PASS
```

**验证:**
```bash
kubectl get secrets -n hermes-agent | grep -E "redis-secret|orchestrator-secret|admin-internal"
```

## Step 3: 升级 Redis 连接 (零停机方案)

> **策略:** 先更新所有 Gateway 的 SWARM_REDIS_URL 为带密码版本。
> 此时 Redis 还没有密码，Redis 7 在未设置 requirepass 时会接受任意 AUTH 请求
> （含密码连接也能成功）。然后再升级 Redis 添加密码。
> **窗口期: 无。** Gateway 先适配 → Redis 再加密码。

### 3.1 更新 Gateway 的 Redis 连接 (先执行!)

> 此步骤会触发 13 个 Gateway 逐一滚动重启。每个约 10-20 秒。
> Redis 当前无密码，Gateway 带密码连接到无密码 Redis 是安全的（Redis 7 接受）。

```bash
# === 在 183 上执行 ===

# 获取 Redis 密码
REDIS_PASS=$(kubectl get secret hermes-redis-secret -n hermes-agent -o jsonpath='{.data.redis-password}' | base64 -d)

# 批量更新 13 个 Gateway 的 SWARM_REDIS_URL
for i in $(seq 1 13); do
  echo "Updating gateway-$i..."
  kubectl set env deploy/hermes-gateway-$i -n hermes-agent \
    "SWARM_REDIS_URL=redis://:${REDIS_PASS}@hermes-redis:6379/0" \
    "SKILL_REPORT_INTERVAL=300" \
    "SKILL_REPORT_ADMIN_URL=http://hermes-admin:48082" \
    --overwrite
done

# 等待所有 Gateway 就绪
for i in $(seq 1 13); do
  echo -n "gateway-$i: "
  kubectl rollout status deploy/hermes-gateway-$i -n hermes-agent --timeout=120s
done
```

**验证:**
```bash
kubectl get pods -n hermes-agent | grep gateway | grep -v Running
# 应无输出 (全部 Running)
```

### 3.2 升级 Redis Deployment (添加密码认证)

> Gateway 已经配置了带密码连接，所以 Redis 加密码后不会中断。
> **重要:** Redis command 使用 shell wrapper 以正确解析 $REDIS_PASSWORD 环境变量。

```bash
# === 在 183 上执行 ===

# 备份当前 Redis deployment
kubectl get deploy hermes-redis -n hermes-agent -o yaml > /tmp/redis-deploy-backup.yaml

# 已确认: hermes-redis-pvc 存在且 Bound (5Gi)，直接使用

# 应用新配置
kubectl apply -f - <<REDIS_YAML
apiVersion: v1
kind: ConfigMap
metadata:
  name: hermes-redis-config
  namespace: hermes-agent
data:
  redis.conf: |
    bind 0.0.0.0
    port 6379
    timeout 300
    tcp-keepalive 60
    appendonly yes
    appendfilename "appendonly.aof"
    appendfsync everysec
    dir /data
    maxmemory 256mb
    maxmemory-policy allkeys-lru
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hermes-redis
  namespace: hermes-agent
spec:
  replicas: 1
  selector:
    matchLabels:
      app: hermes-redis
  strategy:
    type: Recreate
  template:
    metadata:
      labels:
        app: hermes-redis
    spec:
      containers:
      - name: redis
        image: redis:7-alpine
        imagePullPolicy: Never
        command: ["/bin/sh", "-c", "exec redis-server /etc/redis/redis.conf --requirepass $REDIS_PASSWORD"]
        env:
        - name: REDIS_PASSWORD
          valueFrom:
            secretKeyRef:
              name: hermes-redis-secret
              key: redis-password
        ports:
        - containerPort: 6379
        readinessProbe:
          exec:
            command: ["/bin/sh", "-c", "redis-cli -a $REDIS_PASSWORD ping | grep -q PONG"]
          initialDelaySeconds: 5
          periodSeconds: 10
        livenessProbe:
          exec:
            command: ["/bin/sh", "-c", "redis-cli -a $REDIS_PASSWORD ping | grep -q PONG"]
          initialDelaySeconds: 15
          periodSeconds: 20
        resources:
          limits:
            cpu: 500m
            memory: 512Mi
          requests:
            cpu: 100m
            memory: 128Mi
        volumeMounts:
        - name: redis-data
          mountPath: /data
        - name: redis-config
          mountPath: /etc/redis
      volumes:
      - name: redis-data
        persistentVolumeClaim:
          claimName: hermes-redis-pvc
      - name: redis-config
        configMap:
          name: hermes-redis-config
REDIS_YAML
```

> Redis PVC `hermes-redis-pvc` 已确认存在（5Gi，Bound），数据会保留。

**验证:**
```bash
# 等待 Redis 就绪
kubectl rollout status deploy/hermes-redis -n hermes-agent --timeout=60s

# 测试密码连接（使用 REDISCLI_AUTH 避免密码泄露到进程参数）
REDIS_PASS=$(kubectl get secret hermes-redis-secret -n hermes-agent -o jsonpath='{.data.redis-password}' | base64 -d)
kubectl exec -n hermes-agent deploy/hermes-redis -- env REDISCLI_AUTH="$REDIS_PASS" redis-cli ping
# 预期输出: PONG

# 验证无密码被拒绝
kubectl exec -n hermes-agent deploy/hermes-redis -- redis-cli ping 2>&1
# 预期包含: NOAUTH
unset REDIS_PASS
```

### 3.3 Redis NetworkPolicy

```bash
# 限制只有 admin, orchestrator, gateway 可以访问 Redis
kubectl apply -f - <<'REDIS_NP'
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: hermes-redis-netpol
  namespace: hermes-agent
spec:
  podSelector:
    matchLabels:
      app: hermes-redis
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: hermes-admin
    - podSelector:
        matchLabels:
          app: hermes-orchestrator
    - podSelector:
        matchLabels:
          app: hermes-gateway
    ports:
    - protocol: TCP
      port: 6379
REDIS_NP
```

## Step 4: 部署 Orchestrator (新增)

```bash
# === 在 183 上执行 ===

kubectl apply -f - <<'ORCH_YAML'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hermes-orchestrator
  namespace: hermes-agent
spec:
  replicas: 1
  selector:
    matchLabels:
      app: hermes-orchestrator
  template:
    metadata:
      labels:
        app: hermes-orchestrator
    spec:
      serviceAccountName: hermes-orchestrator
      containers:
      - name: orchestrator
        image: hermes-orchestrator:latest
        imagePullPolicy: Never
        env:
        - name: ORCHESTRATOR_API_KEY
          valueFrom:
            secretKeyRef:
              name: hermes-orchestrator-secret
              key: ORCHESTRATOR_API_KEY
        - name: REDIS_URL
          valueFrom:
            secretKeyRef:
              name: hermes-redis-secret
              key: redis-url
        - name: GATEWAY_API_KEY
          valueFrom:
            secretKeyRef:
              name: hermes-db-secret
              key: api_key
        - name: K8S_NAMESPACE
          value: "hermes-agent"
        - name: LOG_LEVEL
          value: "INFO"
        - name: ADMIN_INTERNAL_URL
          value: "http://hermes-admin:48082"
        - name: ADMIN_INTERNAL_TOKEN
          valueFrom:
            secretKeyRef:
              name: hermes-admin-internal-secret
              key: admin_internal_token
        ports:
        - containerPort: 8080
        readinessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 10
        resources:
          limits:
            cpu: "500m"
            memory: "512Mi"
          requests:
            cpu: "100m"
            memory: "256Mi"
---
apiVersion: v1
kind: Service
metadata:
  name: hermes-orchestrator
  namespace: hermes-agent
spec:
  selector:
    app: hermes-orchestrator
  ports:
  - port: 8080
    targetPort: 8080
  type: ClusterIP
ORCH_YAML
```

### 4.1 Orchestrator RBAC + NetworkPolicy

```bash
# === 在 183 上执行 ===

# RBAC
kubectl apply -f - <<'RBAC_YAML'
apiVersion: v1
kind: ServiceAccount
metadata:
  name: hermes-orchestrator
  namespace: hermes-agent
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: hermes-orchestrator-role
  namespace: hermes-agent
rules:
- apiGroups: ["", "apps"]
  resources: ["pods", "deployments", "services"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list"]
  resourceNames: ["hermes-gateway-1-secret","hermes-gateway-2-secret","hermes-gateway-3-secret","hermes-gateway-4-secret","hermes-gateway-5-secret","hermes-gateway-6-secret","hermes-gateway-7-secret","hermes-gateway-8-secret","hermes-gateway-9-secret","hermes-gateway-10-secret","hermes-gateway-11-secret","hermes-gateway-12-secret","hermes-gateway-13-secret"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: hermes-orchestrator-binding
  namespace: hermes-agent
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: hermes-orchestrator-role
subjects:
- kind: ServiceAccount
  name: hermes-orchestrator
  namespace: hermes-agent
RBAC_YAML

# NetworkPolicy — 只允许 admin 和 gateway 访问 orchestrator
kubectl apply -f - <<'NP_YAML'
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: hermes-orchestrator-netpol
  namespace: hermes-agent
spec:
  podSelector:
    matchLabels:
      app: hermes-orchestrator
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: hermes-admin
    ports:
    - protocol: TCP
      port: 8080
NP_YAML
```

**验证:**
```bash
kubectl rollout status deploy/hermes-orchestrator -n hermes-agent --timeout=60s
kubectl logs deploy/hermes-orchestrator -n hermes-agent --tail=20
# 检查日志无报错
```

## Step 5: 升级 Admin Deployment

> **警告:** Admin 代码中 DATABASE_URL 默认值使用 184 的密码 `hermes_pg_2024`。
> 如果不设置此环境变量，Admin 会用错误密码连接 183 的 Postgres 导致启动失败。
> 此步骤中必须包含 DATABASE_URL。

```bash
# === 在 183 上执行 ===

# 获取 Orchestrator API Key
ORCH_KEY=$(kubectl get secret hermes-orchestrator-secret -n hermes-agent -o jsonpath='{.data.ORCHESTRATOR_API_KEY}' | base64 -d)

# 获取 Ingress NodePort（用于 EXTERNAL_URL_PREFIX）
INGRESS_PORT=$(kubectl get svc -A -o jsonpath='{range .items[*]}{.spec.type}{"\t"}{.spec.ports[0].nodePort}{"\n"}{end}' | grep NodePort | head -1 | awk '{print $2}')
EXTERNAL_PORT=${INGRESS_PORT:-40080}
echo "EXTERNAL_URL 将使用端口: $EXTERNAL_PORT"

# 备份当前 Admin 配置 + Service + Ingress
kubectl get deploy hermes-admin -n hermes-agent -o yaml > /tmp/admin-deploy-backup.yaml
kubectl get svc hermes-admin -n hermes-agent -o yaml > /tmp/admin-svc-backup.yaml
kubectl get ingress hermes-ingress -n hermes-agent -o yaml > /tmp/ingress-backup.yaml

# 检查当前 Admin env vars（避免重复添加）
echo "当前 Admin env vars:"
kubectl get deploy hermes-admin -n hermes-agent -o jsonpath='{.spec.template.spec.containers[0].env[*].name}' | tr ' ' '\n'

# 更新镜像
kubectl set image deploy/hermes-admin -n hermes-agent admin=hermes-admin:latest

# 逐个添加/更新环境变量
kubectl set env deploy/hermes-admin -n hermes-agent \
  "EXTERNAL_URL_PREFIX=http://172.32.153.183:${EXTERNAL_PORT}" \
  --overwrite

# DATABASE_URL 从 Secret 引用（不暴露明文密码）
kubectl patch deploy hermes-admin -n hermes-agent --type=json -p='[{
  "op": "add",
  "path": "/spec/template/spec/containers/0/env/-",
  "value": {
    "name": "DATABASE_URL",
    "valueFrom": {
      "secretKeyRef": {
        "name": "hermes-database-secret",
        "key": "database-url"
      }
    }
  }
}]'

# REDIS_PASSWORD 必须在 SWARM_REDIS_URL 之前定义（K8s $(VAR) 插值要求）
kubectl set env deploy/hermes-admin -n hermes-agent \
  "REDIS_PASSWORD=$(kubectl get secret hermes-redis-secret -n hermes-agent -o jsonpath='{.data.redis-password}' | base64 -d)" \
  --overwrite

kubectl set env deploy/hermes-admin -n hermes-agent \
  "SWARM_REDIS_URL=redis://:\$(REDIS_PASSWORD)@hermes-redis:6379/0" \
  "ORCHESTRATOR_API_KEY=${ORCH_KEY}" \
  "ORCHESTRATOR_INTERNAL_URL=http://hermes-orchestrator:8080" \
  --overwrite

# 清除临时变量
unset ORCH_KEY

# ADMIN_INTERNAL_TOKEN 从 secret 引用
kubectl patch deploy hermes-admin -n hermes-agent --type=json -p='[{
  "op": "add",
  "path": "/spec/template/spec/containers/0/env/-",
  "value": {
    "name": "ADMIN_INTERNAL_TOKEN",
    "valueFrom": {
      "secretKeyRef": {
        "name": "hermes-admin-internal-secret",
        "key": "admin_internal_token"
      }
    }
  }
}]'

# CORS — 限制允许的来源
kubectl set env deploy/hermes-admin -n hermes-agent \
  "ADMIN_CORS_ORIGINS=http://172.32.153.183:${EXTERNAL_PORT}" \
  --overwrite
```

**验证:**
```bash
kubectl rollout status deploy/hermes-admin -n hermes-agent --timeout=120s

# 检查 Admin 日志，确认 DB 连接和表创建
kubectl logs deploy/hermes-admin -n hermes-agent --tail=30 | grep -iE "database|table|started|error"

# 检查数据库表已自动创建
kubectl exec -n hermes-agent statefulset/postgres -- \
  psql -U hermes -d hermes_admin -c "\dt"
# 预期: users, agent_metadata, agent_skills, skill_report_ids
```

## Step 6: 统一 Service 和 Ingress 配置

> **顺序重要:** 先配置 Ingress 路由（确保流量可达），再修改 Service 类型（移除 NodePort 直接访问）。

### 6.1 更新 Ingress (添加 /admin/assets/ path)

```bash
# === 在 183 上执行 ===
kubectl patch ingress hermes-ingress -n hermes-agent --type=json -p='[
  {"op":"add","path":"/spec/rules/0/http/paths/-","value":{
    "backend":{"service":{"name":"hermes-admin","port":{"number":48082}}},
    "path":"/admin/assets/",
    "pathType":"Prefix"
  }}
]'
```

### 6.2 创建 WebUI Ingress

```bash
# === 在 183 上执行 ===
kubectl apply -f - <<'WEBUI_INGRESS'
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: hermes-webui-ingress
  namespace: hermes-agent
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /$2
spec:
  ingressClassName: nginx
  rules:
  - http:
      paths:
      - backend:
          service:
            name: hermes-webui
            port:
              number: 8080
        path: /webui(/|$)(.*)
        pathType: Prefix
WEBUI_INGRESS
```

### 6.3 Admin Service: NodePort → ClusterIP

> 在 Ingress 路由配置完成后再修改 Service 类型，避免出现访问中断窗口。

```bash
# === 在 183 上执行 ===
kubectl patch svc hermes-admin -n hermes-agent -p '{"spec":{"type":"ClusterIP"}}'
```

**验证:**
```bash
kubectl get ingress -n hermes-agent
# 预期: hermes-ingress + hermes-webui-ingress
```

## Step 7: 最终验证

```bash
# === 在 183 上执行 ===

# 1. 所有 Pod 状态
kubectl get pods -n hermes-agent
# 预期: 全部 Running

# 2. Admin 健康（使用 Ingress NodePort）
INGRESS_PORT=$(kubectl get svc -A -o jsonpath='{range .items[*]}{.spec.type}{"\t"}{.spec.ports[0].nodePort}{"\n"}{end}' | grep NodePort | head -1 | awk '{print $2}')
curl -s http://172.32.153.183:${INGRESS_PORT}/admin/api/health
# 预期: JSON 响应

# 3. 数据库表
kubectl exec -n hermes-agent statefulset/postgres -- \
  psql -U hermes -d hermes_admin -c "\dt"
# 预期: users, agent_metadata, agent_skills, skill_report_ids

# 4. Agent 元数据自动发现 (等 Admin Discovery Loop 一个周期后检查，约 30-60 秒)
sleep 60
kubectl exec -n hermes-agent statefulset/postgres -- \
  psql -U hermes -d hermes_admin -c "SELECT agent_number, display_name, domain FROM agent_metadata;"
# 预期: 13 个 agent 的 metadata 记录

# 5. Gateway 数量
kubectl get deploy -n hermes-agent | grep gateway | wc -l
# 预期: 13

# 6. Redis 密码连接
REDIS_PASS=$(kubectl get secret hermes-redis-secret -n hermes-agent -o jsonpath='{.data.redis-password}' | base64 -d)
kubectl exec -n hermes-agent deploy/hermes-redis -- env REDISCLI_AUTH="$REDIS_PASS" redis-cli ping
# 预期: PONG
unset REDIS_PASS

# 7. 浏览器访问 Admin 面板
echo "Admin URL: http://172.32.153.183:${INGRESS_PORT}/admin/"
```

## 回滚方案

如果迁移失败，按以下步骤回滚：

```bash
# === 在 183 上执行 ===

export HISTFILE=/dev/null

# 0. 恢复 Gateway 的 SWARM_REDIS_URL 为无密码版本
for i in $(seq 1 13); do
  kubectl set env deploy/hermes-gateway-$i -n hermes-agent \
    "SWARM_REDIS_URL=redis://hermes-redis:6379/0" \
    --overwrite
  # 移除新增的 env
  kubectl set env deploy/hermes-gateway-$i -n hermes-agent \
    SKILL_REPORT_INTERVAL- \
    SKILL_REPORT_ADMIN_URL- \
    --overwrite 2>/dev/null || true
done

# 1. 回滚 Admin Deployment
kubectl apply -f /tmp/admin-deploy-backup.yaml

# 2. 回滚 Admin Service (NodePort)
kubectl apply -f /tmp/admin-svc-backup.yaml

# 3. 回滚 Ingress
kubectl apply -f /tmp/ingress-backup.yaml

# 4. 回滚 Redis
kubectl apply -f /tmp/redis-deploy-backup.yaml

# 5. 删除新增的 Orchestrator
kubectl delete deploy hermes-orchestrator -n hermes-agent 2>/dev/null
kubectl delete svc hermes-orchestrator -n hermes-agent 2>/dev/null
kubectl delete networkpolicy hermes-orchestrator-netpol -n hermes-agent 2>/dev/null
kubectl delete rolebinding hermes-orchestrator-binding -n hermes-agent 2>/dev/null
kubectl delete role hermes-orchestrator-role -n hermes-agent 2>/dev/null
kubectl delete serviceaccount hermes-orchestrator -n hermes-agent 2>/dev/null

# 6. 删除新增的 NetworkPolicy
kubectl delete networkpolicy hermes-redis-netpol -n hermes-agent 2>/dev/null

# 7. 删除新增的 ConfigMap
kubectl delete configmap hermes-redis-config -n hermes-agent 2>/dev/null

# 8. 删除新增的 Secrets
kubectl delete secret hermes-redis-secret hermes-orchestrator-secret hermes-admin-internal-secret hermes-database-secret -n hermes-agent 2>/dev/null

# 9. 删除 WebUI Ingress
kubectl delete ingress hermes-webui-ingress -n hermes-agent 2>/dev/null

echo "回滚完成"
```

## 注意事项

1. **Gateway 允许重启** — 13 个 gateway 会在 Step 3.1 同时重启（约 10-20 秒/个），数据卷保留
2. **数据持久化** — Redis 和 Postgres 使用 PVC/数据卷，重启不丢数据
3. **EXTERNAL_URL** — 183 使用 `172.32.153.183`，184 使用 `172.32.153.184`
4. **DB 密码** — 存储在 `hermes-database-secret` 中，通过 secretKeyRef 引用，不暴露明文
5. **DATABASE_URL 必须设置** — Admin 代码默认值使用 184 密码，不设置会连接失败
6. **Redis shell wrapper** — Redis command 使用 `/bin/sh -c` 以正确解析 $REDIS_PASSWORD
7. **自动建表** — Admin 启动时 SQLAlchemy 自动创建所有表，无需手动 SQL
8. **自动发现** — Admin Discovery Loop 自动读取 K8s annotations 写入 agent_metadata（约 30-60 秒）
9. **REDIS_PASSWORD 先于 SWARM_REDIS_URL** — K8s `$(VAR)` 插值要求变量在同一 env 列表中先定义
10. **所有密钥通过 secretKeyRef 引用** — DATABASE_URL、GATEWAY_API_KEY、ORCHESTRATOR_API_KEY 均不暴露明文
11. **bash 历史已禁用** — 前置条件中执行了 `export HISTFILE=/dev/null`

#!/usr/bin/env bash
# WebUI diagnostics for the 184 development cluster
# Usage: ./webui-diagnose.sh [check-user-email|check-id-mismatch|restart|provision-status]
set -euo pipefail

ACTION="${1:-status}"

case "$ACTION" in
  status)
    echo "=== WebUI Pod Status ==="
    kubectl -n hermes-agent get pods -l app=hermes-webui -o wide
    echo ""
    echo "=== WebUI Pod Logs (last 20) ==="
    kubectl -n hermes-agent logs deploy/hermes-webui --tail=20
    ;;

  check-id-mismatch)
    echo "=== Checking user/auth ID consistency ==="
    kubectl -n hermes-agent exec deploy/hermes-webui -- python3 -c "
import sqlite3
conn = sqlite3.connect('/app/backend/data/webui.db')
for uid, email in conn.execute('SELECT id, email FROM user').fetchall():
    auth = conn.execute('SELECT id FROM auth WHERE email=?', (email,)).fetchone()
    if auth and uid != auth[0]:
        print(f'MISMATCH: {email} user={uid[:8]}... auth={auth[0][:8]}...')
    elif not auth:
        print(f'NO AUTH: {email}')
print('ID check complete')
"
    ;;

  check-user)
    EMAIL="${2:?Usage: webui-diagnose.sh check-user <email>}"
    echo "=== User: $EMAIL ==="
    kubectl -n hermes-agent exec statefulset/postgres -- psql -U hermes -d hermes_admin -c \
      "SELECT id, email, is_active, agent_id, provisioning_status, provisioning_error FROM users WHERE email='$EMAIL';"
    echo ""
    echo "=== WebUI auth record ==="
    kubectl -n hermes-agent exec deploy/hermes-webui -- python3 -c "
import sqlite3
conn = sqlite3.connect('/app/backend/data/webui.db')
u = conn.execute('SELECT id FROM user WHERE email=?', ('$EMAIL',)).fetchone()
a = conn.execute('SELECT id, active FROM auth WHERE email=?', ('$EMAIL',)).fetchone()
if u: print(f'user.id: {u[0]}')
else: print('user: NOT FOUND')
if a: print(f'auth.id: {a[0]}, active: {a[1]}')
else: print('auth: NOT FOUND')
if u and a and u[0] == a[0]: print('IDs: MATCH')
elif u and a: print('IDs: MISMATCH!')
"
    ;;

  restart)
    echo "Restarting WebUI..."
    kubectl -n hermes-agent rollout restart deploy/hermes-webui
    kubectl -n hermes-agent rollout status deploy/hermes-webui --timeout=60s
    ;;

  provision-status)
    echo "=== All Users Provisioning Status ==="
    kubectl -n hermes-agent exec statefulset/postgres -- psql -U hermes -d hermes_admin -c \
      "SELECT email, is_active, agent_id, provisioning_status, provisioning_error FROM users ORDER BY id;"
    ;;

  *)
    echo "Usage: $0 [status|check-id-mismatch|check-user <email>|restart|provision-status]"
    ;;
esac

#!/usr/bin/env python3
"""
ttl-manager.py: 常驻沙箱 TTL 回收。

每 5 分钟扫描所有活跃 Endpoints，
将超过 TTL 无活动的沙箱标记为待回收。
"""
import os
import time
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from kubernetes import client, config
from kubernetes.client.rest import ApiException

SANDBOX_TTL_MINUTES = int(os.getenv("SANDBOX_TTL_MINUTES", "30"))
K8S_NAMESPACE = os.getenv("K8S_NAMESPACE", "hermes-agent")
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL_SECONDS", "300"))


def get_db_connection():
    db_path = os.getenv("HERMES_DB_PATH", "/opt/data/hermes.db")
    return sqlite3.connect(db_path)


def get_last_activity(user_id: str) -> Optional[datetime]:
    """从沙箱 DB 查询用户最后活跃时间"""
    try:
        conn = get_db_connection()
        cursor = conn.execute(
            "SELECT MAX(created_at) FROM messages WHERE user_id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            return datetime.fromisoformat(row[0])
    except Exception:
        pass
    return None


def delete_batchsandbox(user_id: str) -> bool:
    """删除用户的 BatchSandbox"""
    custom_api = client.CustomObjectsApi()
    batch_name = f"sandbox-{user_id}"
    try:
        custom_api.delete_namespaced_custom_object(
            group="sandbox.opensandbox.io",
            version="v1alpha1",
            namespace=K8S_NAMESPACE,
            plural="batchsandboxes",
            name=batch_name
        )
        return True
    except ApiException as e:
        if e.status == 404:
            return True
        return False


def deregister_endpoints(user_id: str) -> bool:
    """从 Endpoints 注销沙箱"""
    core_v1 = client.CoreV1Api()
    try:
        body = client.V1Endpoints(
            metadata=client.V1ObjectMeta(name=user_id, namespace=K8S_NAMESPACE),
            subsets=[]
        )
        core_v1.patch_endpoints(name=user_id, namespace=K8S_NAMESPACE, body=body)
        return True
    except ApiException as e:
        if e.status == 404:
            return True
        return False


def scan_and_reclaim():
    """扫描并回收超时的沙箱"""
    core_v1 = client.CoreV1Api()
    cutoff = datetime.now() - timedelta(minutes=SANDBOX_TTL_MINUTES)

    try:
        endpoints = core_v1.list_namespaced_endpoints(namespace=K8S_NAMESPACE)
    except ApiException as e:
        print(f"[ttl-manager] Failed to list endpoints: {e}")
        return

    for ep in endpoints.items:
        user_id = ep.metadata.name
        if not user_id.startswith("sandbox-"):
            continue

        last_activity = get_last_activity(user_id)
        if last_activity and last_activity < cutoff:
            print(f"[ttl-manager] Reclaiming sandbox for {user_id} (last activity: {last_activity})")
            delete_batchsandbox(user_id)
            deregister_endpoints(user_id)


def main():
    try:
        config.load_incluster_config()
    except config.ConfigException:
        try:
            config.load_kube_config()
        except config.ConfigException:
            print("[ttl-manager] ERROR: No kubernetes config")
            return

    print(f"[ttl-manager] Starting TTL manager (interval={SCAN_INTERVAL}s, TTL={SANDBOX_TTL_MINUTES}min)")
    while True:
        scan_and_reclaim()
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()

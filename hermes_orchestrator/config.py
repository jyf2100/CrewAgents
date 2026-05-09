import os
import logging
import uuid

logger = logging.getLogger(__name__)

class OrchestratorConfig:
    def __init__(self):
        self.api_key = os.environ.get("ORCHESTRATOR_API_KEY", "")
        if not self.api_key:
            logger.critical("FATAL: ORCHESTRATOR_API_KEY environment variable is required")
            raise SystemExit(1)

        self.redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        self.gateway_api_key = os.environ.get("GATEWAY_API_KEY", "")
        if not self.gateway_api_key:
            logger.warning("GATEWAY_API_KEY not set — gateway requests will be unauthenticated")

        self.k8s_namespace = os.environ.get("K8S_NAMESPACE", "hermes-agent")
        self.gateway_port = int(os.environ.get("GATEWAY_PORT", "8642"))
        self.agent_max_concurrent = int(os.environ.get("AGENT_MAX_CONCURRENT", "10"))
        self.task_max_wait = float(os.environ.get("TASK_MAX_WAIT", "600.0"))
        self.health_base_interval = float(os.environ.get("HEALTH_BASE_INTERVAL", "5.0"))
        self.circuit_failure_threshold = int(os.environ.get("CIRCUIT_FAILURE_THRESHOLD", "3"))
        self.circuit_success_threshold = int(os.environ.get("CIRCUIT_SUCCESS_THRESHOLD", "2"))
        self.circuit_recovery_timeout = float(os.environ.get("CIRCUIT_RECOVERY_TIMEOUT", "30.0"))
        self.database_url = os.environ.get("DATABASE_URL", "")
        # --- Multi-replica support ---
        self.pod_name = os.environ.get(
            "HOSTNAME",
            os.environ.get("POD_NAME", f"local-{uuid.uuid4().hex[:8]}"),
        )
        self.discovery_miss_threshold = int(os.environ.get("DISCOVERY_MISS_THRESHOLD", "3"))
        self.circuit_ttl = int(os.environ.get("CIRCUIT_TTL", "3600"))
        self.leader_ttl = int(os.environ.get("LEADER_TTL", "30"))
        self.leader_renew_interval = float(os.environ.get("LEADER_RENEW_INTERVAL", "10.0"))
        self.log_level = os.environ.get("LOG_LEVEL", "INFO")
        self.cors_origins = [
            o.strip()
            for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
            if o.strip()
        ]

    @property
    def gateway_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.gateway_api_key:
            headers["Authorization"] = f"Bearer {self.gateway_api_key}"
        return headers

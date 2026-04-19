import os
from typing import Optional

import yaml

from models import ResourceSpec, TemplateResponse, TemplateTypeResponse
from constants import PROVIDER_URL_MAP

# Provider -> environment variable name mapping
PROVIDER_KEY_MAP = {
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "zhipuai": "GLM_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "kimi": "MOONSHOT_API_KEY",
    "custom": "CUSTOM_API_KEY",
}


def deployment_name(agent_number: int) -> str:
    """Map agent_number to K8s Deployment name (agent 0 -> hermes-gateway, n -> hermes-gateway-n)."""
    return "hermes-gateway" if agent_number == 0 else f"hermes-gateway-{agent_number}"


class TemplateGenerator:

    def __init__(self, templates_dir: str | None = None):
        if templates_dir is None:
            # Default: templates/ sibling of the backend/ package directory
            # In Docker: __file__ = /app/templates.py -> dirname = /app -> templates_dir = /app/templates/
            self.templates_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "templates"
            )
        else:
            self.templates_dir = templates_dir

    def _read_template(self, name: str) -> str:
        path = os.path.join(self.templates_dir, name)
        if os.path.isfile(path):
            with open(path) as f:
                return f.read()
        return ""

    def _write_template(self, name: str, content: str) -> None:
        os.makedirs(self.templates_dir, exist_ok=True)
        path = os.path.join(self.templates_dir, name)
        with open(path, "w") as f:
            f.write(content)

    def render_env(self, llm_config, extra_env: list | None = None) -> str:
        """Generate .env content from LLM config."""
        lines = []
        if isinstance(llm_config, dict):
            provider = str(llm_config.get('provider', 'openrouter'))
            api_key = llm_config.get('api_key', '')
        else:
            provider = llm_config.provider.value if hasattr(llm_config.provider, 'value') else str(llm_config.provider)
            api_key = llm_config.api_key

        # Read template as base
        template = self._read_template(".env.template")
        lines.append(template if template else "# Hermes Agent Environment Configuration\n")

        # Inject API key
        env_key = PROVIDER_KEY_MAP.get(provider, "CUSTOM_API_KEY")
        lines.append(f"\n{env_key}={api_key}\n")

        if extra_env:
            lines.append("\n# Additional environment variables\n")
            for v in extra_env:
                k = v.key if hasattr(v, 'key') else v['key']
                val = v.value if hasattr(v, 'value') else v['value']
                lines.append(f"{k}={val}\n")

        return "".join(lines)

    def render_config_yaml(self, default_model: str = "anthropic/claude-sonnet-4-20250514",
                           provider: str = "openrouter", base_url: str | None = None,
                           terminal_enabled: bool = True, browser_enabled: bool = False,
                           streaming_enabled: bool = True, memory_enabled: bool = True,
                           session_reset_enabled: bool = False) -> str:
        """Generate config.yaml content."""
        provider = provider.value if hasattr(provider, "value") else provider
        resolved_url = base_url or PROVIDER_URL_MAP.get(provider, PROVIDER_URL_MAP["openrouter"])
        config_data = {
            "model": {
                "default": default_model,
                "provider": provider,
                "base_url": resolved_url,
            },
            "terminal": {"enabled": terminal_enabled},
            "browser": {"enabled": browser_enabled},
            "streaming": {"enabled": streaming_enabled},
            "memory": {"enabled": memory_enabled},
            "session_reset": {"enabled": session_reset_enabled},
        }
        return yaml.dump(config_data, default_flow_style=False, allow_unicode=True)

    def render_deployment(self, agent_number: int, secret_name: str,
                          resources: ResourceSpec, namespace: str = "hermes-agent") -> dict:
        """Return a dict for K8s Deployment creation."""
        name = deployment_name(agent_number)
        return {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": name, "namespace": namespace},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app": name}},
                "template": {
                    "metadata": {"labels": {"app": name}},
                    "spec": {
                        "serviceAccountName": "hermes-gateway",
                        "containers": [{
                            "name": "gateway",
                            "image": "nousresearch/hermes-agent:latest",
                            "imagePullPolicy": "IfNotPresent",
                            "args": ["gateway"],
                            "ports": [{"containerPort": 8642}],
                            "env": [
                                {"name": "API_SERVER_ENABLED", "value": "true"},
                                {"name": "API_SERVER_HOST", "value": "0.0.0.0"},
                                {"name": "API_SERVER_PORT", "value": "8642"},
                                {"name": "API_SERVER_KEY", "valueFrom": {
                                    "secretKeyRef": {"name": secret_name, "key": "api_key"}
                                }},
                                {"name": "GATEWAY_ALLOW_ALL_USERS", "value": "true"},
                                {"name": "K8S_NAMESPACE", "value": namespace},
                                {"name": "SANDBOX_POOL_NAME", "value": "hermes-sandbox-pool"},
                                {"name": "SANDBOX_TTL_MINUTES", "value": "30"},
                            ],
                            "resources": {
                                "requests": {"cpu": resources.cpu_request, "memory": resources.memory_request},
                                "limits": {"cpu": resources.cpu_limit, "memory": resources.memory_limit},
                            },
                            "readinessProbe": {
                                "httpGet": {"path": "/health", "port": 8642},
                                "initialDelaySeconds": 60, "periodSeconds": 10,
                                "timeoutSeconds": 5, "failureThreshold": 6,
                            },
                            "livenessProbe": {
                                "httpGet": {"path": "/health", "port": 8642},
                                "initialDelaySeconds": 120, "periodSeconds": 30,
                                "timeoutSeconds": 10, "failureThreshold": 5,
                            },
                            "volumeMounts": [{"name": "hermes-data", "mountPath": "/opt/data"}],
                        }],
                        "volumes": [{
                            "name": "hermes-data",
                            "hostPath": {
                                "path": f"/data/hermes/agent{agent_number}",
                                "type": "DirectoryOrCreate",
                            },
                        }],
                    },
                },
            },
        }

    def render_service(self, agent_number: int, namespace: str = "hermes-agent") -> dict:
        name = deployment_name(agent_number)
        return {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": name, "namespace": namespace},
            "spec": {
                "type": "ClusterIP",
                "ports": [{"name": "api", "port": 8642, "targetPort": 8642}],
                "selector": {"app": name},
            },
        }

    def get_all(self) -> TemplateResponse:
        return TemplateResponse(
            deployment_yaml=self._read_template("deployment.yaml"),
            env_template=self._read_template(".env.template"),
            config_yaml_template=self._read_template("config.yaml.template"),
            soul_md_template=self._read_template("SOUL.md.template"),
        )

    _FILE_MAP = {
        "deployment": "deployment.yaml",
        "env": ".env.template",
        "config": "config.yaml.template",
        "soul": "SOUL.md.template",
    }

    def get_template(self, template_type: str) -> str:
        filename = self._FILE_MAP.get(template_type)
        if not filename:
            raise ValueError(f"Unknown template type: {template_type}")
        return self._read_template(filename)

    def set_template(self, template_type: str, content: str) -> None:
        filename = self._FILE_MAP.get(template_type)
        if not filename:
            raise ValueError(f"Unknown template type: {template_type}")
        self._write_template(filename, content)

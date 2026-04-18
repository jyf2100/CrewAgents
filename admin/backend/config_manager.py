import os
import re

from fastapi import HTTPException

from models import EnvVariable, EnvReadResponse, ConfigYaml, SoulMarkdown

SECRET_PATTERNS = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)", re.IGNORECASE)

BLOCKED_ENV_KEYS = {
    "PATH", "HOME", "USER", "SHELL", "LD_PRELOAD", "LD_LIBRARY_PATH",
    "PYTHONPATH", "PYTHONHOME", "HOSTNAME", "TERM", "LANG", "LC_ALL",
    "PWD", "OLDPWD", "MAIL", "LOGNAME", "SSH_AUTH_SOCK", "DISPLAY",
    "XDG_RUNTIME_DIR", "container", "KUBERNETES_SERVICE_HOST",
    "KUBERNETES_SERVICE_PORT",
}


class ConfigManager:
    def __init__(self, data_root: str = "/data/hermes"):
        self.data_root = data_root

    def _agent_dir(self, agent_id: int) -> str:
        return os.path.join(self.data_root, f"agent{agent_id}")

    def read_env(self, agent_id: int) -> EnvReadResponse:
        env_path = os.path.join(self._agent_dir(agent_id), ".env")
        if not os.path.isfile(env_path):
            return EnvReadResponse(agent_number=agent_id, variables=[])
        variables = []
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("\"'")
                is_secret = bool(SECRET_PATTERNS.search(key))
                if is_secret:
                    variables.append(EnvVariable(key=key, value="****", masked=True, is_secret=True))
                else:
                    variables.append(EnvVariable(key=key, value=value, masked=False, is_secret=False))
        return EnvReadResponse(agent_number=agent_id, variables=variables)

    def write_env(self, agent_id: int, updates: list[EnvVariable]) -> None:
        blocked = [v.key for v in updates if v.key in BLOCKED_ENV_KEYS]
        if blocked:
            raise HTTPException(400, f"Cannot set blocked environment variable(s): {', '.join(blocked)}")
        env_path = os.path.join(self._agent_dir(agent_id), ".env")
        os.makedirs(os.path.dirname(env_path), exist_ok=True)
        lines: list[str] = []
        if os.path.isfile(env_path):
            with open(env_path) as f:
                lines = f.readlines()
        update_map = {v.key: v.value for v in updates}
        updated_keys: set[str] = set()
        new_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                new_lines.append(line)
                continue
            if "=" in stripped:
                key, _, _ = stripped.partition("=")
                key = key.strip()
                if key in update_map:
                    new_lines.append(f"{key}={update_map[key]}\n")
                    updated_keys.add(key)
                    continue
            new_lines.append(line)
        for key, value in update_map.items():
            if key not in updated_keys:
                new_lines.append(f"{key}={value}\n")
        tmp_path = env_path + ".tmp"
        with open(tmp_path, "w") as f:
            f.writelines(new_lines)
        os.replace(tmp_path, env_path)

    def read_config(self, agent_id: int) -> ConfigYaml:
        path = os.path.join(self._agent_dir(agent_id), "config.yaml")
        if not os.path.isfile(path):
            return ConfigYaml(content="# No config.yaml found")
        with open(path) as f:
            return ConfigYaml(content=f.read())

    async def write_config(self, agent_id: int, content: str) -> None:
        import yaml
        try:
            yaml.safe_load(content)
        except yaml.YAMLError as e:
            raise HTTPException(400, f"Invalid YAML: {e}")
        path = os.path.join(self._agent_dir(agent_id), "config.yaml")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w") as f:
            f.write(content)
        os.replace(tmp_path, path)

    def read_soul(self, agent_id: int) -> SoulMarkdown:
        path = os.path.join(self._agent_dir(agent_id), "SOUL.md")
        if not os.path.isfile(path):
            return SoulMarkdown(content="")
        with open(path) as f:
            return SoulMarkdown(content=f.read())

    async def write_soul(self, agent_id: int, content: str) -> None:
        path = os.path.join(self._agent_dir(agent_id), "SOUL.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w") as f:
            f.write(content)
        os.replace(tmp_path, path)

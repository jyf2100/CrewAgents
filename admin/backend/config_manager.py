import os

from fastapi import HTTPException

from models import EnvVariable, EnvReadResponse, ConfigYaml, SoulMarkdown
from constants import SECRET_PATTERNS, BLOCKED_ENV_KEYS


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

    def read_env_raw(self, agent_id: int) -> dict[str, str]:
        """Read .env file without masking secrets. Returns {key: value} dict."""
        env_path = os.path.join(self._agent_dir(agent_id), ".env")
        if not os.path.isfile(env_path):
            return {}
        result: dict[str, str] = {}
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                result[key.strip()] = value.strip().strip("\"'")
        return result

    def remove_env_keys(self, agent_id: int, key_prefix: str) -> None:
        """Remove all env vars whose key starts with key_prefix."""
        env_path = os.path.join(self._agent_dir(agent_id), ".env")
        if not os.path.isfile(env_path):
            return
        with open(env_path) as f:
            lines = f.readlines()
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped and "=" in stripped and stripped.partition("=")[0].strip().startswith(key_prefix):
                continue
            new_lines.append(line)
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

    def write_config(self, agent_id: int, content: str) -> None:
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

    def write_soul(self, agent_id: int, content: str) -> None:
        path = os.path.join(self._agent_dir(agent_id), "SOUL.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w") as f:
            f.write(content)
        os.replace(tmp_path, path)

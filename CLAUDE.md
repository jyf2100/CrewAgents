# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Reference

```bash
# Install
uv venv venv --python 3.11 && source venv/bin/activate
uv pip install -e ".[all,dev]"

# Test
python -m pytest tests/ -q                           # Full suite (~3 min, parallel)
python -m pytest tests/test_model_tools.py::test_fn  # Single test
python -m pytest tests/tools/ -q                     # Tool tests only

# Run
hermes                     # Interactive CLI
hermes gateway             # Messaging gateway

# Docker
docker build -t hermes-agent .
docker-compose up

# Admin panel (K8s)
cd admin && docker build -f backend/Dockerfile -t hermes-admin:latest .
docker save hermes-admin:latest | sudo ctr -n k8s.io images import -
kubectl apply -k kubernetes/
```

## Architecture

This is Hermes Agent — a multi-platform AI agent with 20+ messaging adapters, 40+ tools, and K8s-based multi-instance deployment.

```
User (Telegram/Discord/Slack/WhatsApp/CLI/...)
  → Gateway (gateway/run.py) — async platform adapters
    → AIAgent (run_agent.py) — synchronous agent loop, LLM API calls
      → Tool Registry (tools/registry.py) — self-registering tools
        → Tool Backends (tools/environments/) — local/docker/SSH/Modal/Daytona
```

**Key entry points** (from `pyproject.toml`): `hermes` → CLI, `hermes-agent` → direct agent, `hermes-acp` → VS Code/JetBrains adapter.

**Admin Panel** (`admin/`): Separate FastAPI + React app that manages K8s agent instances (CRUD, config, health, logs). Talks to K8s API via python client. Built with multi-stage Dockerfile (`admin/backend/Dockerfile`).

**OpenSandbox** (`OpenSandbox/`): Git submodule with K8s CRDs for sandboxed code execution. Has its own AGENTS.md.

See `AGENTS.md` and `CONTRIBUTING.md` for comprehensive developer guides.

## Critical Rules

### Path Handling
- **Always use `get_hermes_home()` from `hermes_constants`** — never hardcode `~/.hermes`. Profile support means the home dir can be anywhere. There are 119+ references; hardcoding caused 5 bugs in PR #3575.
- Use `display_hermes_home()` for user-facing messages.

### Agent Loop
- **Entirely synchronous** (not async) despite async gateway adapters. The gateway bridges this.
- **Never alter past context mid-conversation** — prompt caching is critical for cost. Only exception: context compression.

### Testing
- Autouse fixture `_isolate_hermes_home` redirects `~/.hermes/` to temp dir — tests never write to real home.
- API keys are cleared in CI. Never rely on real keys in tests.
- Integration tests excluded by default (`-m 'not integration'`).
- 30-second global test timeout enforced.

### Tool Registration
Tools self-register at import time via `tools/registry.py`. To add a tool: create the module, add to `_modules` list in `model_tools.py`. Tool schema descriptions must not cross-reference other tools by name (may be unavailable).

### Terminal/Display
- **`simple_term_menu` is banned** — rendering bugs in tmux/iTerm2. Use `curses`.
- **`\033[K` (ANSI erase-to-EOL) is banned** in spinner code — leaks as literal text under `prompt_toolkit`.

### Config System
Three separate loaders exist: `load_cli_config()` in `cli.py`, `load_config()` in `hermes_cli/config.py`, direct YAML load in `gateway/run.py`. Changes must consider all three.

## K8s Deployment

Namespace: `hermes-agent`. Three gateway instances by default (gateway, gateway2, gateway3), each with own volume and API key.

Key ports: `8642` (gateway API), `48080` (Open WebUI), `48082` (admin panel).

Admin deployment uses `imagePullPolicy: Never` — import images to containerd:
```bash
docker save hermes-admin:latest | sudo ctr -n k8s.io images import -
```

RBAC: Admin ClusterRole needs `metrics.k8s.io` permissions for resource monitoring. See `admin/kubernetes/rbac.yaml`.

## Project-Specific Pitfalls

- **`_last_resolved_tool_names`** in `model_tools.py` is process-global. Delegate tool saves/restores it around subagent runs.
- **Skills** have conditional activation via `fallback_for_toolsets`, `requires_toolsets` in YAML frontmatter, evaluated at prompt build time.
- **Skin system** (`hermes_cli/skin_engine.py`) is pure data — YAML drop-in to `~/.hermes/skins/`.
- **`yaml.dump()`** serializes Python enums as `!!python/object/apply:` tags. Always convert to `.value` first.


## 开发环境
1、172.32.153.184是当前开发服务器可以sudo -u root
2、编译打包镜像注意用国内源
3、github下载使用 代理 http_proxy=http://172.32.147.190:7890

## 测试环境
172.32.153.183  当前服务器上可以ssh root@172.32.153.183
from __future__ import annotations
import json
import logging
import time
from typing import TYPE_CHECKING

import aiohttp

from hermes_orchestrator.models.task import Task, TaskResult, RunResult

if TYPE_CHECKING:
    from hermes_orchestrator.config import OrchestratorConfig

logger = logging.getLogger(__name__)

class GatewayOverloadedError(Exception):
    pass

class TaskSubmissionError(Exception):
    pass

class TaskTimeoutError(Exception):
    pass

class RunNotFoundError(Exception):
    pass

class TaskExecutor:
    def __init__(self, config: OrchestratorConfig):
        self._config = config

    async def submit_run(self, gateway_url: str, prompt: str, instructions: str = "") -> str:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{gateway_url}/v1/runs",
                json={"input": prompt, "instructions": instructions},
                headers=self._config.gateway_headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 429:
                    raise GatewayOverloadedError("Gateway concurrent run limit reached")
                if resp.status != 202:
                    body = await resp.text()
                    raise TaskSubmissionError(f"Gateway returned {resp.status}: {body}")
                data = await resp.json()
                return data["run_id"]

    async def consume_run_events(self, gateway_url: str, run_id: str, max_wait: float = 0) -> RunResult:
        if max_wait <= 0:
            max_wait = self._config.task_max_wait
        deadline = time.monotonic() + max_wait
        output = ""

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{gateway_url}/v1/runs/{run_id}/events",
                headers=self._config.gateway_headers,
                timeout=aiohttp.ClientTimeout(total=max_wait),
            ) as resp:
                if resp.status != 200:
                    raise RunNotFoundError(f"Run {run_id} not found on gateway")

                async for line in resp.content:
                    if time.monotonic() > deadline:
                        raise TaskTimeoutError(f"Run {run_id} timed out")
                    line = line.strip()
                    if not line.startswith(b"data: "):
                        continue
                    event = json.loads(line[6:])
                    evt = event.get("event", "")

                    if evt == "message.delta":
                        output += event.get("delta", "")
                    elif evt == "reasoning.available":
                        logger.debug("Run %s: reasoning (%d chars)", run_id, len(event.get("text", "")))
                    elif evt == "tool.started":
                        logger.info("Run %s: tool %s started", run_id, event.get("tool"))
                    elif evt == "tool.completed":
                        logger.info("Run %s: tool %s completed", run_id, event.get("tool"))
                    elif evt == "run.completed":
                        return RunResult(
                            run_id=run_id, status="completed",
                            output=event.get("output", output),
                            usage=event.get("usage"),
                        )
                    elif evt == "run.failed":
                        return RunResult(
                            run_id=run_id, status="failed",
                            error=event.get("error", "Unknown error"),
                        )

        raise TaskTimeoutError(f"Run {run_id} stream ended without completion")

    def extract_result(self, event: dict, task: Task) -> TaskResult:
        return TaskResult(
            content=event.get("output", ""),
            usage=event.get("usage", {}),
            duration_seconds=time.time() - task.created_at,
            run_id=event.get("run_id", ""),
        )

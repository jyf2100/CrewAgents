"""File browser — read-only filesystem access to agent pods."""
from __future__ import annotations

import os
import logging

from fastapi import APIRouter, HTTPException, Query, Request

from auth import auth
from models import FileListResponse, FileReadResponse
from path_utils import validate_path as _validate_path, check_file_rate_limit

logger = logging.getLogger("hermes-admin.file_browser")

router = APIRouter()

MAX_READ_SIZE = 1 * 1024 * 1024  # 1MB for text preview
MAX_DOWNLOAD_SIZE = 50 * 1024 * 1024  # 50MB hard limit


def _get_effective_agent_id(request: Request, agent_id: int) -> int:
    override = getattr(request.state, "agent_id", None)
    return override if override is not None else agent_id


async def _find_running_pod(agent_id: int) -> str:
    from main import k8s
    deployment_name = f"hermes-gateway-{agent_id}"
    pods = await k8s.get_pods_for_deployment(deployment_name)
    for pod in pods:
        if pod.status.phase == "Running":
            return pod.metadata.name
    raise HTTPException(status_code=404, detail="No running pod found for agent")


@router.get("/agents/{agent_id}/files/list", dependencies=[auth], response_model=FileListResponse)
async def list_files(request: Request, agent_id: int, path: str = Query("/home")):
    effective_id = _get_effective_agent_id(request, agent_id)
    check_file_rate_limit(effective_id)
    safe_path = _validate_path(path)
    pod_name = await _find_running_pod(effective_id)

    from main import k8s
    entries = await k8s.list_dir(pod_name, safe_path)
    return {"path": safe_path, "entries": entries}


@router.get("/agents/{agent_id}/files/read", dependencies=[auth], response_model=FileReadResponse)
async def read_file(request: Request, agent_id: int, path: str = Query(...)):
    effective_id = _get_effective_agent_id(request, agent_id)
    check_file_rate_limit(effective_id)
    safe_path = _validate_path(path)

    basename = os.path.basename(safe_path)
    if not basename:
        raise HTTPException(status_code=400, detail="Cannot read a directory")

    pod_name = await _find_running_pod(effective_id)

    from main import k8s

    # Size precheck to prevent memory DoS
    file_size = await k8s.get_file_size(pod_name, safe_path)
    if file_size < 0:
        raise HTTPException(status_code=404, detail="File not found")
    if file_size > MAX_DOWNLOAD_SIZE:
        return {
            "path": safe_path,
            "content": None,
            "size": file_size,
            "truncated": True,
            "message": f"File too large ({file_size} bytes). Maximum is {MAX_DOWNLOAD_SIZE // (1024*1024)}MB.",
        }

    content_bytes, error = await k8s.read_file_from_pod(pod_name, safe_path)
    if error:
        safe_error = "File not found" if "not found" in error.lower() else "Access denied"
        raise HTTPException(status_code=404, detail=safe_error)

    if len(content_bytes) > MAX_READ_SIZE:
        return {
            "path": safe_path,
            "content": None,
            "size": len(content_bytes),
            "truncated": True,
            "message": f"File too large for preview ({len(content_bytes)} bytes). Use download instead.",
        }

    try:
        text = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "path": safe_path,
            "content": None,
            "size": len(content_bytes),
            "truncated": False,
            "binary": True,
            "message": "Binary file — use download instead.",
        }

    return {"path": safe_path, "content": text, "size": len(content_bytes), "truncated": False}

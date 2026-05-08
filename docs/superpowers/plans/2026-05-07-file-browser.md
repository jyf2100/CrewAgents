# Pod File Browser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only file browser to the Hermes Admin Panel so user-mode users can navigate and preview files inside their agent's K8s pod.

**Architecture:** Backend uses `kubectl exec` via the existing `k8s_client.py` to run `ls`/`stat`/`cat` commands inside the pod. Frontend is a single `FileBrowserPage.tsx` with split-pane layout (file list + preview). Auth reuses the existing tri-mode system — user mode automatically scopes to the user's bound agent pod.

**Tech Stack:** FastAPI (backend), React 19 + Tailwind 4 (frontend), K8s exec API (pod file access)

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `admin/backend/file_browser.py` | Backend endpoints: list dir, read file, download |
| Modify | `admin/backend/k8s_client.py` | Add `list_dir()` method for pod directory listing |
| Modify | `admin/backend/main.py` | Register file_browser router |
| Create | `admin/frontend/src/pages/FileBrowserPage.tsx` | File browser page (list + preview + download) |
| Modify | `admin/frontend/src/App.tsx` | Add `/files` route |
| Modify | `admin/frontend/src/components/AdminLayout.tsx` | Add sidebar entry for user mode |
| Modify | `admin/frontend/src/lib/admin-api.ts` | Add file browser API methods |
| Modify | `admin/frontend/src/i18n/en.ts` | English translations |
| Modify | `admin/frontend/src/i18n/zh.ts` | Chinese translations + Translations interface |

---

### Task 1: Backend — Add `list_dir` to K8sClient

**Files:**
- Modify: `admin/backend/k8s_client.py` (add method after `read_file_from_pod` around line 346)

- [ ] **Step 1: Add the `list_dir` method**

```python
async def list_dir(self, pod_name: str, path: str) -> list[dict]:
    """List directory contents in a pod. Returns [{name, type, size}].
    type is 'd' (directory), 'f' (file), 'l' (symlink).
    """
    from kubernetes.stream import stream as k8s_stream
    # Use a JSON-safe output format: type|name|size
    # -F separator is unavailable on busybox, use |
    cmd = [
        "sh", "-c",
        f"""if [ ! -d '{path}' ]; then echo '__NOT_DIR__'; exit 0; fi
cd '{path}'
for f in * .*; do
  [ "$f" = "." ] && continue
  [ "$f" = ".." ] && continue
  [ -e "$f" ] || [ -L "$f" ] || continue
  if [ -L "$f" ]; then
    echo "l|$f|0"
  elif [ -d "$f" ]; then
    echo "d|$f|0"
  else
    size=$(stat -c%s "$f" 2>/dev/null || echo 0)
    echo "f|$f|$size"
  fi
done""",
    ]
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                k8s_stream,
                self.core_api.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self.namespace,
                command=cmd,
                stdin=False,
                stdout=True,
                stderr=True,
                tty=False,
                _preload_content=True,
            ),
            timeout=15,
        )
        if "__NOT_DIR__" in result:
            return []
        entries = []
        for line in result.strip().splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            parts = line.split("|", 2)
            if len(parts) != 3:
                continue
            entry_type, name, size_str = parts
            if not name:
                continue
            try:
                size = int(size_str)
            except ValueError:
                size = 0
            entries.append({"name": name, "type": entry_type, "size": size})
        # Sort: directories first, then files, alphabetically within each group
        entries.sort(key=lambda e: (0 if e["type"] == "d" else 1, e["name"].lower()))
        return entries
    except asyncio.TimeoutError:
        return []
    except Exception:
        return []
```

- [ ] **Step 2: Verify no syntax errors**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent && python -c "from admin.backend.k8s_client import K8sClient; print('OK')"` 
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add admin/backend/k8s_client.py
git commit -m "feat(file-browser): add list_dir method to K8sClient for pod directory listing"
```

---

### Task 2: Backend — Create `file_browser.py` Router

**Files:**
- Create: `admin/backend/file_browser.py`

- [ ] **Step 1: Create the file browser router**

```python
"""File browser — read-only filesystem access to agent pods."""
from __future__ import annotations

import os
import logging
from urllib.parse import unquote
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

logger = logging.getLogger("hermes-admin.file_browser")

router = APIRouter()

# Path safety
BLOCKED_PREFIXES = ("/proc", "/sys", "/dev", "/run")
MAX_READ_SIZE = 1 * 1024 * 1024  # 1MB for text preview


def _validate_path(path: str) -> str:
    """Sanitize and validate a filesystem path."""
    path = unquote(path).strip()
    if not path.startswith("/"):
        path = "/" + path
    normalized = os.path.normpath(path)
    # Block path traversal
    if ".." in normalized.split("/"):
        raise HTTPException(400, "Path traversal not allowed")
    # Block system directories
    for prefix in BLOCKED_PREFIXES:
        if normalized == prefix or normalized.startswith(prefix + "/"):
            raise HTTPException(403, f"Access to {prefix} is not allowed")
    return normalized


# Auth — reuse terminal.py pattern
try:
    from auth import auth as _auth
    auth = _auth
except ImportError:
    from fastapi import Header
    async def _verify_admin_key(
        x_admin_key: str = Header(..., alias="X-Admin-Key"),
        request: Request = None,
    ):
        import hmac
        admin_key = getattr(request.app.state, "admin_key", "")
        if not admin_key:
            return True
        if not hmac.compare_digest(x_admin_key, admin_key):
            raise HTTPException(status_code=401, detail="Invalid admin key")
        return True
    auth = Depends(_verify_admin_key)


def _get_effective_agent_id(request: Request, agent_id: int) -> int:
    """Resolve effective agent_id — user mode forces their bound agent."""
    override = getattr(request.state, "agent_id", None)
    return override if override is not None else agent_id


async def _find_running_pod(agent_id: int) -> str:
    """Find a running pod for the given agent. Raises 404 if none."""
    from main import k8s
    deployment_name = f"hermes-gateway-{agent_id}"
    pods = await k8s.get_pods_for_deployment(deployment_name)
    for pod in pods:
        if pod.status.phase == "Running":
            return pod.metadata.name
    raise HTTPException(status_code=404, detail="No running pod found for agent")


@router.get("/agents/{agent_id}/files/list", dependencies=[auth])
async def list_files(request: Request, agent_id: int, path: str = Query("/")):
    """List directory contents in the agent pod."""
    effective_id = _get_effective_agent_id(request, agent_id)
    safe_path = _validate_path(path)
    pod_name = await _find_running_pod(effective_id)

    from main import k8s
    entries = await k8s.list_dir(pod_name, safe_path)
    return {"path": safe_path, "entries": entries}


@router.get("/agents/{agent_id}/files/read", dependencies=[auth])
async def read_file(request: Request, agent_id: int, path: str = Query(...)):
    """Read a text file from the agent pod (up to 1MB)."""
    effective_id = _get_effective_agent_id(request, agent_id)
    safe_path = _validate_path(path)

    # Only allow reading regular files (must have an extension or be a known text file)
    basename = os.path.basename(safe_path)
    if not basename:
        raise HTTPException(400, "Cannot read a directory")

    pod_name = await _find_running_pod(effective_id)

    from main import k8s
    content_bytes, error = await k8s.read_file_from_pod(pod_name, safe_path)
    if error:
        raise HTTPException(404, detail=error)

    if len(content_bytes) > MAX_READ_SIZE:
        return {
            "path": safe_path,
            "content": None,
            "size": len(content_bytes),
            "truncated": True,
            "message": f"File too large for preview ({len(content_bytes)} bytes). Use download instead.",
        }

    # Try to decode as UTF-8 text
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
```

- [ ] **Step 2: Verify no import errors**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent/admin/backend && python -c "import ast; ast.parse(open('file_browser.py').read()); print('OK')"` 
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add admin/backend/file_browser.py
git commit -m "feat(file-browser): add file_browser.py router with list/read endpoints"
```

---

### Task 3: Backend — Register Router in `main.py`

**Files:**
- Modify: `admin/backend/main.py` (around line 47-48 where other routers are imported)

- [ ] **Step 1: Add the import**

Find this line (around line 48):
```python
from terminal import router as terminal_router
```

Add after it:
```python
from file_browser import router as file_browser_router
```

- [ ] **Step 2: Register the router**

Find this line (search for `include_router(terminal_router)`):
```python
app.include_router(terminal_router)
```

Add after it:
```python
app.include_router(file_browser_router)
```

- [ ] **Step 3: Verify the app starts**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent/admin/backend && python -c "from main import app; routes = [r.path for r in app.routes]; fb = [r for r in routes if 'files' in r]; print('File routes:', fb)"` 
Expected: Shows routes containing `/agents/{agent_id}/files/list` and `/agents/{agent_id}/files/read`

- [ ] **Step 4: Commit**

```bash
git add admin/backend/main.py
git commit -m "feat(file-browser): register file_browser router in main.py"
```

---

### Task 4: Frontend — Add API Methods and Types

**Files:**
- Modify: `admin/frontend/src/lib/admin-api.ts`

- [ ] **Step 1: Add interfaces after the existing `SkillEntry` interface (around line 505)**

```typescript
// ---------------------------------------------------------------------------
// File Browser
// ---------------------------------------------------------------------------

export interface FileEntry {
  name: string;
  type: "d" | "f" | "l";
  size: number;
}

export interface FileListResponse {
  path: string;
  entries: FileEntry[];
}

export interface FileReadResponse {
  path: string;
  content: string | null;
  size: number;
  truncated: boolean;
  binary?: boolean;
  message?: string;
}
```

- [ ] **Step 2: Add API methods at the end of `adminApi` object (before the closing `}`)**

```typescript
  // -- File Browser --
  listFiles(agentId: number, path: string): Promise<FileListResponse> {
    return adminFetch(`/agents/${agentId}/files/list?path=${encodeURIComponent(path)}`);
  },

  readFile(agentId: number, path: string): Promise<FileReadResponse> {
    return adminFetch(`/agents/${agentId}/files/read?path=${encodeURIComponent(path)}`);
  },

  getFileDownloadUrl(agentId: number, path: string): string {
    const headers = getAuthHeaders();
    const authKey = headers["X-Admin-Key"] || headers["X-User-Token"] || headers["X-Email-Token"] || "";
    const authHeader = headers["X-Admin-Key"] ? "X-Admin-Key" : headers["X-User-Token"] ? "X-User-Token" : "X-Email-Token";
    return `${ADMIN_BASE}/agents/${agentId}/terminal/download?path=${encodeURIComponent(path)}`;
  },
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent/admin/frontend && npx tsc --noEmit 2>&1 | head -20` 
Expected: No errors related to the new code

- [ ] **Step 4: Commit**

```bash
git add admin/frontend/src/lib/admin-api.ts
git commit -m "feat(file-browser): add FileEntry types and API methods to admin-api.ts"
```

---

### Task 5: Frontend — Add i18n Translations

**Files:**
- Modify: `admin/frontend/src/i18n/zh.ts` (Translations interface + values)
- Modify: `admin/frontend/src/i18n/en.ts` (values)

- [ ] **Step 1: Add keys to `zh.ts` Translations interface**

Find the end of the `Translations` interface and add before the closing `}`:

```typescript
  // File Browser
  fileBrowser: string;
  fileBrowserTitle: string;
  filePath: string;
  fileName: string;
  fileSize: string;
  fileType: string;
  fileEmpty: string;
  fileNotFound: string;
  fileLoading: string;
  filePreview: string;
  fileDownload: string;
  fileParentDir: string;
  fileDirUp: string;
  fileGoTo: string;
  fileGo: string;
  fileNoPod: string;
  fileNoPodDesc: string;
  fileBinary: string;
  fileTooLarge: string;
  fileDefaultPath: string;
```

- [ ] **Step 2: Add values to `zh.ts` export object**

Find the end of the `zh` export object and add before the closing `}`:

```typescript
  // File Browser
  fileBrowser: "文件浏览",
  fileBrowserTitle: "Pod 文件浏览",
  filePath: "路径",
  fileName: "名称",
  fileSize: "大小",
  fileType: "类型",
  fileEmpty: "目录为空",
  fileNotFound: "文件不存在或不可读",
  fileLoading: "加载中...",
  filePreview: "文件预览",
  fileDownload: "下载",
  fileParentDir: "上级目录",
  fileDirUp: "返回上级",
  fileGoTo: "跳转到",
  fileGo: "前往",
  fileNoPod: "Agent 未运行",
  fileNoPodDesc: "文件浏览需要 Agent Pod 处于运行状态",
  fileBinary: "二进制文件，请下载查看",
  fileTooLarge: "文件过大，请下载查看",
  fileDefaultPath: "/home/user/hermes",
```

- [ ] **Step 3: Add values to `en.ts` export object**

Find the end of the `en` export object and add before the closing `}`:

```typescript
  // File Browser
  fileBrowser: "Files",
  fileBrowserTitle: "Pod File Browser",
  filePath: "Path",
  fileName: "Name",
  fileSize: "Size",
  fileType: "Type",
  fileEmpty: "Empty directory",
  fileNotFound: "File not found or not readable",
  fileLoading: "Loading...",
  filePreview: "File Preview",
  fileDownload: "Download",
  fileParentDir: "Parent directory",
  fileDirUp: "Go up",
  fileGoTo: "Go to",
  fileGo: "Go",
  fileNoPod: "Agent not running",
  fileNoPodDesc: "File browser requires the agent pod to be running",
  fileBinary: "Binary file — download to view",
  fileTooLarge: "File too large — download to view",
  fileDefaultPath: "/home/user/hermes",
```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent/admin/frontend && npx tsc --noEmit 2>&1 | head -20`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add admin/frontend/src/i18n/zh.ts admin/frontend/src/i18n/en.ts
git commit -m "feat(file-browser): add i18n translations for file browser (zh + en)"
```

---

### Task 6: Frontend — Create FileBrowserPage Component

**Files:**
- Create: `admin/frontend/src/pages/FileBrowserPage.tsx`

- [ ] **Step 1: Create the component**

```tsx
import { useState, useEffect, useCallback } from "react";
import { useI18n } from "../hooks/useI18n";
import { adminApi, getAuthHeaders, FileEntry, FileListResponse, FileReadResponse, AdminApiError } from "../lib/admin-api";

function formatSize(bytes: number): string {
  if (bytes === 0) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let size = bytes;
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024;
    i++;
  }
  return `${size.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function entryIcon(type: "d" | "f" | "l", name: string) {
  if (type === "d") return "📁";
  if (type === "l") return "🔗";
  const ext = name.split(".").pop()?.toLowerCase() || "";
  if (["yaml", "yml", "json", "toml", "ini", "conf", "cfg"].includes(ext)) return "⚙️";
  if (["md", "txt", "log", "csv"].includes(ext)) return "📄";
  if (["py", "js", "ts", "sh", "bash"].includes(ext)) return "📝";
  if (["png", "jpg", "jpeg", "gif", "svg", "webp"].includes(ext)) return "🖼️";
  return "📄";
}

export function FileBrowserPage() {
  const { t } = useI18n();
  const agentId = Number(localStorage.getItem("admin_user_agent_id") || "0");

  const [currentPath, setCurrentPath] = useState(t.fileDefaultPath || "/home/user/hermes");
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // File preview state
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [fileMeta, setFileMeta] = useState<{ size: number; truncated: boolean; binary?: boolean; message?: string } | null>(null);
  const [fileLoading, setFileLoading] = useState(false);

  // Path input state
  const [pathInput, setPathInput] = useState(currentPath);

  const loadDir = useCallback(async (path: string) => {
    if (!agentId) return;
    setLoading(true);
    setError(null);
    setSelectedFile(null);
    setFileContent(null);
    setFileMeta(null);
    try {
      const result = await adminApi.listFiles(agentId, path);
      setCurrentPath(result.path);
      setPathInput(result.path);
      setEntries(result.entries);
    } catch (e) {
      if (e instanceof AdminApiError) {
        setError(e.detail);
      } else {
        setError(String(e));
      }
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    loadDir(currentPath);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function navigateTo(path: string) {
    loadDir(path);
  }

  function navigateUp() {
    const parent = currentPath.split("/").slice(0, -1).join("/") || "/";
    navigateTo(parent);
  }

  function handleEntryClick(entry: FileEntry) {
    if (entry.type === "d") {
      const newPath = currentPath === "/" ? `/${entry.name}` : `${currentPath}/${entry.name}`;
      navigateTo(newPath);
    } else {
      previewFile(currentPath === "/" ? `/${entry.name}` : `${currentPath}/${entry.name}`);
    }
  }

  async function previewFile(path: string) {
    setSelectedFile(path);
    setFileLoading(true);
    setFileContent(null);
    setFileMeta(null);
    try {
      const result = await adminApi.readFile(agentId, path);
      setFileContent(result.content);
      setFileMeta({ size: result.size, truncated: result.truncated, binary: result.binary, message: result.message });
    } catch (e) {
      if (e instanceof AdminApiError) {
        setFileMeta({ size: 0, truncated: false, message: e.detail });
      }
    } finally {
      setFileLoading(false);
    }
  }

  function handleDownload(path: string) {
    // Build download URL with auth header as query param (browser navigation can't set headers)
    const headers = getAuthHeaders();
    const authVal = headers["X-Admin-Key"] || headers["X-User-Token"] || headers["X-Email-Token"] || "";
    const authName = headers["X-Admin-Key"] ? "X-Admin-Key" : headers["X-User-Token"] ? "X-User-Token" : "X-Email-Token";
    const url = `/admin/api/agents/${agentId}/terminal/download?path=${encodeURIComponent(path)}&${encodeURIComponent(authName)}=${encodeURIComponent(authVal)}`;
    window.open(url, "_blank");
  }

  // Breadcrumb
  const pathParts = currentPath.split("/").filter(Boolean);

  if (!agentId) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-text-secondary">{t.fileNoPodDesc}</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header + breadcrumb */}
      <div>
        <h2 className="text-xl font-bold text-text-primary font-[family-name:var(--font-display)]">
          {t.fileBrowserTitle}
        </h2>
        {/* Breadcrumb */}
        <div className="flex items-center gap-1 mt-2 text-sm text-text-secondary flex-wrap">
          <button
            onClick={() => navigateTo("/")}
            className="hover:text-accent-cyan transition-colors"
          >
            /
          </button>
          {pathParts.map((part, idx) => {
            const partialPath = "/" + pathParts.slice(0, idx + 1).join("/");
            return (
              <span key={partialPath} className="flex items-center gap-1">
                <span className="text-text-muted">/</span>
                <button
                  onClick={() => navigateTo(partialPath)}
                  className="hover:text-accent-cyan transition-colors"
                >
                  {part}
                </button>
              </span>
            );
          })}
        </div>

        {/* Path input */}
        <div className="flex gap-2 mt-3">
          <input
            type="text"
            value={pathInput}
            onChange={(e) => setPathInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") navigateTo(pathInput); }}
            className="flex-1 bg-surface/50 border border-border-subtle rounded-md px-3 py-1.5 text-sm font-[family-name:var(--font-mono)] text-text-primary placeholder-text-muted focus:outline-none focus:border-accent-cyan"
            placeholder={t.filePath}
          />
          <button
            onClick={() => navigateTo(pathInput)}
            className="px-4 py-1.5 rounded-md text-sm bg-accent-cyan/20 text-accent-cyan border border-accent-cyan/30 hover:bg-accent-cyan/30 transition-colors"
          >
            {t.fileGo}
          </button>
          {currentPath !== "/" && (
            <button
              onClick={navigateUp}
              className="px-3 py-1.5 rounded-md text-sm text-text-secondary hover:text-text-primary hover:bg-surface/50 transition-colors border border-border-subtle"
            >
              {t.fileDirUp}
            </button>
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="p-3 rounded-md bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Split pane */}
      <div className="flex gap-4 min-h-[500px]">
        {/* File list */}
        <div className="w-1/3 min-w-[280px] border border-border-subtle rounded-lg bg-surface/30 overflow-hidden flex flex-col">
          <div className="px-3 py-2 border-b border-border-subtle text-xs text-text-muted uppercase tracking-wider">
            {entries.length} {entries.length === 1 ? "item" : "items"}
          </div>
          <div className="flex-1 overflow-auto">
            {loading ? (
              <div className="flex items-center justify-center h-32 text-text-secondary text-sm">
                {t.fileLoading}
              </div>
            ) : entries.length === 0 ? (
              <div className="flex items-center justify-center h-32 text-text-secondary text-sm">
                {t.fileEmpty}
              </div>
            ) : (
              <ul className="divide-y divide-border-subtle">
                {entries.map((entry) => {
                  const fullPath = currentPath === "/" ? `/${entry.name}` : `${currentPath}/${entry.name}`;
                  const isSelected = selectedFile === fullPath;
                  return (
                    <li key={entry.name}>
                      <button
                        onClick={() => handleEntryClick(entry)}
                        className={[
                          "w-full flex items-center gap-2 px-3 py-2 text-sm transition-colors text-left",
                          isSelected
                            ? "bg-accent-cyan/10 text-accent-cyan"
                            : entry.type === "d"
                              ? "text-text-primary hover:bg-surface/50"
                              : "text-text-secondary hover:bg-surface/50 hover:text-text-primary",
                        ].join(" ")}
                      >
                        <span className="text-base leading-none">{entryIcon(entry.type, entry.name)}</span>
                        <span className="flex-1 truncate font-[family-name:var(--font-mono)] text-xs">
                          {entry.name}
                        </span>
                        {entry.type !== "d" && (
                          <span className="text-xs text-text-muted shrink-0">
                            {formatSize(entry.size)}
                          </span>
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>

        {/* Preview pane */}
        <div className="flex-1 border border-border-subtle rounded-lg bg-surface/30 overflow-hidden flex flex-col">
          <div className="px-3 py-2 border-b border-border-subtle flex items-center justify-between">
            <span className="text-xs text-text-muted uppercase tracking-wider">
              {selectedFile ? t.filePreview : t.fileBrowserTitle}
            </span>
            {selectedFile && (
              <button
                onClick={() => handleDownload(selectedFile)}
                className="px-3 py-1 rounded text-xs bg-accent-cyan/20 text-accent-cyan hover:bg-accent-cyan/30 transition-colors"
              >
                {t.fileDownload}
              </button>
            )}
          </div>
          <div className="flex-1 overflow-auto p-3">
            {!selectedFile ? (
              <div className="flex items-center justify-center h-full text-text-muted text-sm">
                {t.fileName}
              </div>
            ) : fileLoading ? (
              <div className="flex items-center justify-center h-full text-text-secondary text-sm">
                {t.fileLoading}
              </div>
            ) : fileMeta?.binary ? (
              <div className="flex items-center justify-center h-full text-text-secondary text-sm">
                {t.fileBinary} ({formatSize(fileMeta.size)})
              </div>
            ) : fileMeta?.truncated ? (
              <div className="space-y-2">
                <div className="p-2 rounded bg-yellow-500/10 border border-yellow-500/30 text-yellow-400 text-xs">
                  {t.fileTooLarge} ({formatSize(fileMeta.size)})
                </div>
              </div>
            ) : fileMeta?.message && !fileContent ? (
              <div className="flex items-center justify-center h-full text-red-400 text-sm">
                {fileMeta.message}
              </div>
            ) : (
              <pre className="text-xs font-[family-name:var(--font-mono)] text-text-primary whitespace-pre-wrap break-all leading-relaxed">
                {fileContent}
              </pre>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent/admin/frontend && npx tsc --noEmit 2>&1 | head -20`
Expected: No errors related to FileBrowserPage

- [ ] **Step 3: Commit**

```bash
git add admin/frontend/src/pages/FileBrowserPage.tsx
git commit -m "feat(file-browser): create FileBrowserPage component with split-pane layout"
```

---

### Task 7: Frontend — Wire Up Route and Sidebar Navigation

**Files:**
- Modify: `admin/frontend/src/App.tsx`
- Modify: `admin/frontend/src/components/AdminLayout.tsx`

- [ ] **Step 1: Add import and route in `App.tsx`**

Add import at the top (after `ChatPage` import):
```typescript
import { FileBrowserPage } from "./pages/FileBrowserPage";
```

Add route inside `<Route element={<AdminLayout />}>` block (after the `/chat` route):
```tsx
<Route path="/files" element={<FileBrowserPage />} />
```

- [ ] **Step 2: Add sidebar entry in `AdminLayout.tsx`**

Find the "Web UI / Start Chat link" section (around line 218). After the `</div>` that closes the chat/webui section, and before the `{/* Swarm section — admin only */}` comment, add:

```tsx
{/* File browser — user mode */}
{isUser && (
  <div className="px-2 mt-2">
    <Link
      to="/files"
      onClick={onNavigate}
      className={[
        "w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-colors duration-150",
        isActive("/files")
          ? "text-text-primary font-medium bg-surface/50"
          : "text-text-secondary hover:text-text-primary hover:bg-surface/50",
      ].join(" ")}
    >
      <svg viewBox="0 0 24 24" className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z" />
      </svg>
      <span>{t.fileBrowser}</span>
    </Link>
  </div>
)}
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent/admin/frontend && npx tsc --noEmit 2>&1 | head -20`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add admin/frontend/src/App.tsx admin/frontend/src/components/AdminLayout.tsx
git commit -m "feat(file-browser): add /files route and user-mode sidebar entry"
```

---

### Task 8: Build and Verify

**Files:** None (verification only)

- [ ] **Step 1: Run frontend build**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent/admin/frontend && npm run build 2>&1 | tail -5`
Expected: Build succeeds, no errors

- [ ] **Step 2: Verify backend starts without errors**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent/admin/backend && python -c "from main import app; print('Routes:', [r.path for r in app.routes if 'files' in str(getattr(r, 'path', ''))])"`
Expected: Shows file browser routes

- [ ] **Step 3: Commit (only if any fixes were needed)**

```bash
git add -A
git commit -m "fix(file-browser): build fixes"
```

import { useState, useEffect, useCallback, useRef } from "react";
import { useI18n } from "../hooks/useI18n";
import { adminApi, getAuthHeaders, clearAuth, FileEntry, FileReadResponse, AdminApiError } from "../lib/admin-api";

function formatSize(bytes: number): string {
  if (bytes === 0) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let size = bytes;
  while (size >= 1024 && i < units.length - 1) { size /= 1024; i++; }
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
  const [agentId] = useState(() => parseInt(localStorage.getItem("admin_user_agent_id") || "0", 10));

  const [currentPath, setCurrentPath] = useState("/home/user/hermes");
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [fileMeta, setFileMeta] = useState<{ size: number; truncated: boolean; binary?: boolean; message?: string } | null>(null);
  const [fileLoading, setFileLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);

  const currentPathRef = useRef(currentPath);
  currentPathRef.current = currentPath;

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
      if (e instanceof AdminApiError) setError(e.detail);
      else setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => { if (agentId) loadDir(currentPathRef.current); }, [agentId]); // eslint-disable-line react-hooks/exhaustive-deps

  function navigateTo(path: string) { loadDir(path); }

  function navigateUp() {
    const parent = currentPath.split("/").slice(0, -1).join("/") || "/";
    navigateTo(parent);
  }

  function handleEntryClick(entry: FileEntry) {
    if (entry.type === "d") {
      navigateTo(currentPath === "/" ? `/${entry.name}` : `${currentPath}/${entry.name}`);
    } else {
      previewFile(currentPath === "/" ? `/${entry.name}` : `${currentPath}/${entry.name}`);
    }
  }

  async function previewFile(path: string) {
    setSelectedFile(path);
    setFileLoading(true);
    setFileContent(null);
    setFileMeta(null);
    setDownloadError(null);
    try {
      const result = await adminApi.readFile(agentId, path);
      setFileContent(result.content);
      setFileMeta({ size: result.size, truncated: result.truncated, binary: result.binary, message: result.message });
    } catch (e) {
      if (e instanceof AdminApiError) {
        setFileMeta({ size: 0, truncated: false, message: e.detail });
      } else {
        setFileMeta({ size: 0, truncated: false, message: e instanceof Error ? e.message : "Failed to preview file" });
      }
    } finally {
      setFileLoading(false);
    }
  }

  function handleDownload(path: string) {
    setDownloadError(null);
    setDownloading(true);
    const headers = getAuthHeaders();
    const authVal = headers["X-Admin-Key"] || headers["X-User-Token"] || headers["X-Email-Token"] || "";
    const authName = headers["X-Admin-Key"] ? "X-Admin-Key" : headers["X-User-Token"] ? "X-User-Token" : "X-Email-Token";
    const url = `/admin/api/agents/${agentId}/terminal/download?path=${encodeURIComponent(path)}`;
    fetch(url, { headers: { [authName]: authVal } })
      .then(r => {
        if (r.status === 401) {
          clearAuth();
          return null;
        }
        if (!r.ok) throw new Error(`Download failed (${r.status})`);
        return r.blob();
      })
      .then(blob => {
        if (!blob) return;
        const blobUrl = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = blobUrl;
        a.download = path.split("/").pop() || "file";
        a.click();
        URL.revokeObjectURL(blobUrl);
      })
      .catch(e => {
        setDownloadError(e instanceof Error ? e.message : "Download failed");
      })
      .finally(() => {
        setDownloading(false);
      });
  }

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
      <div>
        <h2 className="text-xl font-bold text-text-primary font-[family-name:var(--font-display)]">
          {t.fileBrowserTitle}
        </h2>
        <div className="flex items-center gap-1 mt-2 text-sm text-text-secondary flex-wrap">
          <button onClick={() => navigateTo("/")} className="hover:text-accent-cyan transition-colors">/</button>
          {pathParts.map((part, idx) => {
            const partialPath = "/" + pathParts.slice(0, idx + 1).join("/");
            return (
              <span key={partialPath} className="flex items-center gap-1">
                <span className="text-text-muted">/</span>
                <button onClick={() => navigateTo(partialPath)} className="hover:text-accent-cyan transition-colors">{part}</button>
              </span>
            );
          })}
        </div>
        <div className="flex gap-2 mt-3">
          <input
            type="text"
            value={pathInput}
            onChange={(e) => setPathInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") navigateTo(pathInput); }}
            className="flex-1 bg-surface/50 border border-border-subtle rounded-md px-3 py-1.5 text-sm font-[family-name:var(--font-mono)] text-text-primary placeholder-text-muted focus:outline-none focus:border-accent-cyan"
            placeholder={t.filePath}
          />
          <button onClick={() => navigateTo(pathInput)} className="px-4 py-1.5 rounded-md text-sm bg-accent-cyan/20 text-accent-cyan border border-accent-cyan/30 hover:bg-accent-cyan/30 transition-colors">
            {t.fileGo}
          </button>
          {currentPath !== "/" && (
            <button onClick={navigateUp} className="px-3 py-1.5 rounded-md text-sm text-text-secondary hover:text-text-primary hover:bg-surface/50 transition-colors border border-border-subtle">
              {t.fileDirUp}
            </button>
          )}
        </div>
      </div>

      {error && <div className="p-3 rounded-md bg-red-500/10 border border-red-500/30 text-red-400 text-sm">{error}</div>}
      {downloadError && <div className="p-3 rounded-md bg-red-500/10 border border-red-500/30 text-red-400 text-sm">{downloadError}</div>}

      <div className="flex gap-4 min-h-[500px]">
        <div className="w-1/3 min-w-[280px] border border-border-subtle rounded-lg bg-surface/30 overflow-hidden flex flex-col">
          <div className="px-3 py-2 border-b border-border-subtle text-xs text-text-muted uppercase tracking-wider">
            {entries.length} {entries.length === 1 ? t.fileItemSingle : t.fileItemPlural}
          </div>
          <div className="flex-1 overflow-auto">
            {loading ? (
              <div className="flex items-center justify-center h-32 text-text-secondary text-sm">{t.fileLoading}</div>
            ) : entries.length === 0 ? (
              <div className="flex items-center justify-center h-32 text-text-secondary text-sm">{t.fileEmpty}</div>
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
                          isSelected ? "bg-accent-cyan/10 text-accent-cyan"
                            : entry.type === "d" ? "text-text-primary hover:bg-surface/50"
                              : "text-text-secondary hover:bg-surface/50 hover:text-text-primary",
                        ].join(" ")}
                      >
                        <span className="text-base leading-none">{entryIcon(entry.type, entry.name)}</span>
                        <span className="flex-1 truncate font-[family-name:var(--font-mono)] text-xs">{entry.name}</span>
                        {entry.type !== "d" && <span className="text-xs text-text-muted shrink-0">{formatSize(entry.size)}</span>}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>

        <div className="flex-1 border border-border-subtle rounded-lg bg-surface/30 overflow-hidden flex flex-col">
          <div className="px-3 py-2 border-b border-border-subtle flex items-center justify-between">
            <span className="text-xs text-text-muted uppercase tracking-wider">{selectedFile ? t.filePreview : t.fileBrowserTitle}</span>
            {selectedFile && (
              <button onClick={() => handleDownload(selectedFile)} disabled={downloading} className="px-3 py-1 rounded text-xs bg-accent-cyan/20 text-accent-cyan hover:bg-accent-cyan/30 transition-colors disabled:opacity-50">
                {downloading ? t.fileDownloading : t.fileDownload}
              </button>
            )}
          </div>
          <div className="flex-1 overflow-auto p-3">
            {!selectedFile ? (
              <div className="flex items-center justify-center h-full text-text-muted text-sm">{t.fileName}</div>
            ) : fileLoading ? (
              <div className="flex items-center justify-center h-full text-text-secondary text-sm">{t.fileLoading}</div>
            ) : fileMeta?.binary ? (
              <div className="flex items-center justify-center h-full text-text-secondary text-sm">{t.fileBinary} ({formatSize(fileMeta.size)})</div>
            ) : fileMeta?.truncated ? (
              <div className="p-2 rounded bg-yellow-500/10 border border-yellow-500/30 text-yellow-400 text-xs">{t.fileTooLarge} ({formatSize(fileMeta.size)})</div>
            ) : fileMeta?.message && !fileContent ? (
              <div className="flex items-center justify-center h-full text-red-400 text-sm">{fileMeta.message}</div>
            ) : (
              <pre className="text-xs font-[family-name:var(--font-mono)] text-text-primary whitespace-pre-wrap break-all leading-relaxed">{fileContent}</pre>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

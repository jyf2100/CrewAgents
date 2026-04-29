import { useEffect, useRef, useState, useCallback } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import "@xterm/xterm/css/xterm.css";
import { adminApi } from "../lib/admin-api";
import { useI18n } from "../hooks/useI18n";

interface TerminalTabProps {
  agentId: number;
}

type ConnState = "connecting" | "connected" | "disconnected";

const TERMINAL_THEME = {
  background: "#080815",
  foreground: "#d1f7ff",
  cursor: "#05d9e8",
  cursorAccent: "#080815",
  selectionBackground: "rgba(5, 217, 232, 0.3)",
  selectionForeground: "#ffffff",
  black: "#080815",
  red: "#ff2a6d",
  green: "#00ff41",
  yellow: "#f5a623",
  blue: "#05d9e8",
  magenta: "#7b2d8e",
  cyan: "#05d9e8",
  white: "#d1f7ff",
  brightBlack: "#a8a8c0",
  brightRed: "#ff2a6d",
  brightGreen: "#00ff41",
  brightYellow: "#f5a623",
  brightBlue: "#05d9e8",
  brightMagenta: "#7b2d8e",
  brightCyan: "#05d9e8",
  brightWhite: "#d1f7ff",
};

export function TerminalTab({ agentId }: TerminalTabProps) {
  const { t } = useI18n();
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const wsGeneration = useRef(0);
  const [connState, setConnState] = useState<ConnState>("connecting");

  const connect = useCallback(async () => {
    // Clean up previous
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    const generation = ++wsGeneration.current;
    setConnState("connecting");

    try {
      const { token } = await adminApi.getTerminalToken(agentId);
      const url = adminApi.getTerminalWsUrl(agentId, token);
      const ws = new WebSocket(url);
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      ws.onopen = () => {
        if (wsGeneration.current !== generation) return;
        setConnState("connected");
        // Send initial terminal size
        if (termRef.current) {
          const { rows, cols } = termRef.current;
          ws.send(JSON.stringify({ type: "resize", rows, cols }));
        }
      };

      ws.onmessage = (ev) => {
        if (wsGeneration.current !== generation) return;
        if (!termRef.current) return;
        if (ev.data instanceof ArrayBuffer) {
          termRef.current.write(new Uint8Array(ev.data));
        } else if (typeof ev.data === "string") {
          try {
            const obj = JSON.parse(ev.data);
            if (obj.type === "error") {
              termRef.current.writeln(`\r\n\x1b[31m${obj.message}\x1b[0m`);
            }
          } catch {
            termRef.current.write(ev.data);
          }
        }
      };

      ws.onclose = () => {
        if (wsGeneration.current !== generation) return;
        setConnState("disconnected");
        if (termRef.current) {
          termRef.current.writeln("\r\n\x1b[33m--- Connection closed ---\x1b[0m");
        }
      };

      ws.onerror = () => {
        if (wsGeneration.current !== generation) return;
        setConnState("disconnected");
      };
    } catch (e) {
      setConnState("disconnected");
      if (termRef.current) {
        termRef.current.writeln(`\r\n\x1b[31mConnection failed: ${e}\x1b[0m`);
      }
    }
  }, [agentId]);

  // Initialize terminal
  useEffect(() => {
    if (!containerRef.current) return;

    const term = new Terminal({
      theme: TERMINAL_THEME,
      fontFamily: '"JetBrains Mono", monospace',
      fontSize: 13,
      cursorBlink: true,
      cursorStyle: "block",
      convertEol: true,
      scrollback: 5000,
    });

    const fitAddon = new FitAddon();
    const webLinksAddon = new WebLinksAddon();

    term.loadAddon(fitAddon);
    term.loadAddon(webLinksAddon);
    term.open(containerRef.current);

    try {
      fitAddon.fit();
    } catch {
      // ignore fit errors on mount
    }

    termRef.current = term;
    fitRef.current = fitAddon;

    // Send keystrokes to WebSocket
    const dataDisposable = term.onData((data) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(data);
      }
    });

    // Send resize to WebSocket
    const resizeDisposable = term.onResize(({ rows, cols }) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "resize", rows, cols }));
      }
    });

    // ResizeObserver for container size changes
    const observer = new ResizeObserver(() => {
      try {
        fitAddon.fit();
      } catch {
        // ignore
      }
    });
    observer.observe(containerRef.current);

    // Connect
    connect();

    return () => {
      observer.disconnect();
      dataDisposable.dispose();
      resizeDisposable.dispose();
      term.dispose();
      wsRef.current?.close();
      wsRef.current = null;
      termRef.current = null;
      fitRef.current = null;
    };
  }, [connect]);

  const handleReconnect = () => {
    if (termRef.current) {
      termRef.current.clear();
      termRef.current.writeln("\x1b[36mReconnecting...\x1b[0m");
    }
    connect();
  };

  const statusColor =
    connState === "connected"
      ? "bg-green-400"
      : connState === "connecting"
        ? "bg-yellow-400"
        : "bg-red-400";

  const statusText =
    connState === "connected"
      ? t.terminalConnected
      : connState === "connecting"
        ? t.terminalConnecting
        : t.terminalDisconnected;

  return (
    <div className="space-y-3">
      {/* Status bar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`inline-block h-2 w-2 rounded-full ${statusColor} ${connState === "connected" ? "animate-pulse" : ""}`} />
          <span className="text-xs text-secondary">{statusText}</span>
        </div>
        {connState === "disconnected" && (
          <button
            onClick={handleReconnect}
            className="px-3 py-1 text-xs rounded border border-accent-cyan/30 text-accent-cyan hover:bg-accent-cyan/10 transition-colors"
          >
            {t.terminalReconnect}
          </button>
        )}
      </div>

      {/* Terminal container */}
      <div
        ref={containerRef}
        className="rounded-lg border border-accent-cyan/20 overflow-hidden"
        style={{
          height: "500px",
          backgroundColor: "#080815",
        }}
      />
    </div>
  );
}

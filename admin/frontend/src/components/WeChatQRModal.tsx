import { useState, useEffect, useRef, useCallback } from "react";
import { adminApi } from "../lib/admin-api";
import { useI18n } from "../hooks/useI18n";
import { showToast } from "../lib/toast";

type QRStatus =
  | "idle"
  | "loading"
  | "waiting"
  | "scanned"
  | "done"
  | "error"
  | "timeout";

interface WeChatQRModalProps {
  agentId: number;
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export function WeChatQRModal({ agentId, open, onClose, onSuccess }: WeChatQRModalProps) {
  const { t } = useI18n();
  const [status, setStatus] = useState<QRStatus>("idle");
  const [qrUrl, setQrUrl] = useState("");
  const [message, setMessage] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const esRef = useRef<EventSource | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const cleanup = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const startQR = useCallback(() => {
    cleanup();
    setStatus("loading");
    setQrUrl("");
    setMessage("");
    setElapsed(0);

    const url = adminApi.startWeixinQR(agentId);
    const es = new EventSource(url);
    esRef.current = es;

    // Start countdown timer (8 min = 480s)
    timerRef.current = setInterval(() => {
      setElapsed((prev) => {
        if (prev >= 480) {
          cleanup();
          setStatus("timeout");
          setMessage("QR session timed out");
          return prev;
        }
        return prev + 1;
      });
    }, 1000);

    es.addEventListener("qr_ready", (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      setQrUrl(data.qrcode_url);
      setStatus("waiting");
      setMessage("Waiting for scan...");
    });

    es.addEventListener("status_update", (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      if (data.status === "wait") {
        setStatus("waiting");
        setMessage("Waiting for scan...");
      } else if (data.status === "scaned") {
        setStatus("scanned");
        setMessage("Scanned! Confirm on phone...");
      }
    });

    es.addEventListener("qr_refresh", (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      setQrUrl(data.qrcode_url);
      setElapsed(0);
      setStatus("waiting");
      setMessage("QR refreshed, waiting for scan...");
    });

    es.addEventListener("done", () => {
      cleanup();
      setStatus("done");
      setMessage("WeChat connected!");
      showToast(t.weixinConnected || "WeChat connected!");
      setTimeout(() => {
        onSuccess();
        onClose();
      }, 2000);
    });

    es.addEventListener("error", (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      cleanup();
      setStatus("error");
      setMessage(data.message || "Unknown error");
    });

    es.addEventListener("timeout", (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      cleanup();
      setStatus("timeout");
      setMessage(data.message || "Timed out");
    });

    es.onerror = () => {
      if (esRef.current === es) {
        cleanup();
        setStatus("error");
        setMessage("Connection lost");
      }
    };
  }, [agentId, cleanup, onClose, onSuccess, t]);

  useEffect(() => {
    if (open) {
      startQR();
    } else {
      cleanup();
      setStatus("idle");
    }
    return cleanup;
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!open) return null;

  const remaining = Math.max(0, 480 - elapsed);
  const minutes = Math.floor(remaining / 60);
  const seconds = remaining % 60;
  const progressPct = (remaining / 480) * 100;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={onClose}>
      {/* Glass backdrop */}
      <div className="absolute inset-0 bg-background/70 backdrop-blur-md" />

      {/* Modal */}
      <div
        className="relative z-10 w-full max-w-md mx-4 rounded-lg border border-border bg-surface p-6 animate-modal-enter"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-text-primary mb-4">
          {t.weixinQRTitle || "Scan QR with WeChat"}
        </h2>

        {/* QR Code area */}
        <div className="flex flex-col items-center gap-4">
          {status === "loading" && (
            <div className="h-48 w-48 flex items-center justify-center rounded-lg bg-background border border-border">
              <div className="h-6 w-6 border-2 border-accent-cyan border-t-transparent rounded-full animate-spin-slow" />
            </div>
          )}

          {(status === "waiting" || status === "scanned") && qrUrl && (
            <div className="rounded-lg bg-white p-2 border border-border">
              <img
                src={qrUrl}
                alt="WeChat QR Code"
                className="h-48 w-48"
              />
            </div>
          )}

          {(status === "waiting" || status === "scanned") && !qrUrl && (
            <div className="h-48 w-48 flex items-center justify-center rounded-lg bg-background border border-border">
              <span className="text-text-secondary text-sm">Loading QR...</span>
            </div>
          )}

          {status === "done" && (
            <div className="h-48 w-48 flex items-center justify-center rounded-lg bg-success/10 border border-success/30">
              <svg className="h-16 w-16 text-success" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </div>
          )}

          {(status === "error" || status === "timeout") && (
            <div className="h-48 w-48 flex items-center justify-center rounded-lg bg-accent-pink/10 border border-accent-pink/30">
              <svg className="h-16 w-16 text-accent-pink" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </div>
          )}

          {/* Status message */}
          <p className={`text-sm text-center ${
            status === "scanned" ? "text-accent-cyan" :
            status === "done" ? "text-success" :
            status === "error" || status === "timeout" ? "text-accent-pink" :
            "text-text-secondary"
          }`}>
            {message}
          </p>

          {/* Progress bar (only during active QR) */}
          {(status === "waiting" || status === "scanned") && (
            <div className="w-full">
              <div className="h-1.5 rounded-full bg-bar-track overflow-hidden">
                <div
                  className="h-full rounded-full bg-accent-cyan transition-all duration-1000"
                  style={{ width: `${progressPct}%` }}
                />
              </div>
              <div className="flex justify-between mt-1 text-xs text-text-secondary">
                <span>{status === "scanned" ? (t.weixinScanned || "Scanned") : (t.weixinWaiting || "Waiting...")}</span>
                <span className="font-[family-name:var(--font-mono)]">
                  {String(minutes).padStart(2, "0")}:{String(seconds).padStart(2, "0")}
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Action buttons */}
        <div className="flex justify-center gap-3 mt-6">
          {(status === "error" || status === "timeout") && (
            <button
              onClick={startQR}
              className="h-9 px-4 text-sm rounded-lg bg-accent-cyan text-background hover:shadow-[0_0_15px_rgba(5,217,232,0.3)] transition-shadow"
            >
              {t.retry}
            </button>
          )}
          <button
            onClick={onClose}
            className="h-9 px-4 text-sm border border-border text-text-secondary hover:text-text-primary rounded-lg transition-colors"
          >
            {status === "done" ? (t.close || "Close") : t.cancel}
          </button>
        </div>
      </div>
    </div>
  );
}

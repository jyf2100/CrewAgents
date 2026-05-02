import { useState, useEffect } from "react";
import { adminApi, AdminApiError } from "../lib/admin-api";
import { useI18n } from "../hooks/useI18n";

export function ChatPage() {
  const { t } = useI18n();
  const [iframeSrc, setIframeSrc] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await adminApi.getWebUILoginUrl();
        if (cancelled) return;
        const baseUrl = res.url.replace("/api/v1/auths/signin", "");
        const hash = `#email=${encodeURIComponent(res.email)}&password=${encodeURIComponent(res.password)}`;
        setIframeSrc(`${baseUrl}/token-login.html${hash}`);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof AdminApiError && err.status === 400) {
          setError(err.detail);
        } else {
          setError(t.errorGeneric);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [t]);

  if (error) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="glass-heavy rounded-xl border border-border p-8 max-w-md text-center">
          <svg viewBox="0 0 24 24" className="w-12 h-12 mx-auto mb-4 text-accent-pink" fill="none" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
          </svg>
          <p className="text-text-secondary text-sm">{error}</p>
        </div>
      </div>
    );
  }

  if (!iframeSrc) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-text-secondary text-sm animate-pulse">{t.loading}</p>
      </div>
    );
  }

  return (
    <div style={{ height: "calc(100vh - 3.5rem)", marginTop: "-1rem", marginLeft: "-1.5rem", marginRight: "-1.5rem", marginBottom: "-1rem" }}>
      <iframe
        src={iframeSrc}
        className="w-full h-full border-0"
        title="Web Chat"
        sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
      />
    </div>
  );
}

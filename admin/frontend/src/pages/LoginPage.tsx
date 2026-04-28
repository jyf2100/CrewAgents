import { useState, FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { adminApi, setAdminKey } from "../lib/admin-api";
import { useI18n } from "../hooks/useI18n";

export function LoginPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!key.trim()) return;

    setLoading(true);
    setError("");

    try {
      await adminApi.login(key.trim());
      setAdminKey(key.trim());
      navigate("/", { replace: true });
    } catch {
      setError(t.loginFailed);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      {/* Decorative hexagons */}
      <div
        className="absolute top-[15%] left-[12%] w-24 h-24 bg-accent-cyan/10"
        style={{ clipPath: "polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)" }}
        aria-hidden="true"
      />
      <div
        className="absolute bottom-[20%] right-[10%] w-32 h-32 bg-accent-pink/10"
        style={{ clipPath: "polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)" }}
        aria-hidden="true"
      />
      <div
        className="absolute top-[60%] left-[5%] w-16 h-16 bg-accent-cyan/5"
        style={{ clipPath: "polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)" }}
        aria-hidden="true"
      />

      <div className="glass-heavy rounded-xl border border-border p-10 max-w-sm w-full mx-4 relative z-10">
        <h1 className="font-[family-name:var(--font-display)] text-3xl font-bold tracking-[0.15em] text-text-primary glow-pink-text text-center mb-1">
          NEWHERMES
        </h1>
        <p className="font-[family-name:var(--font-body)] text-text-secondary text-sm text-center mb-8">
          {t.loginSubtitle}
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="relative">
            <div className="absolute inset-y-0 left-0 flex items-center pl-3 pointer-events-none">
              <svg
                className="h-4 w-4 text-text-secondary"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={1.5}
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z"
                />
              </svg>
            </div>
            <input
              type="password"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder={t.loginKeyPlaceholder}
              className="w-full h-11 px-4 pl-10 text-sm bg-background border border-border rounded-lg text-text-primary placeholder:text-text-secondary focus:outline-none focus:border-accent-cyan focus:shadow-[0_0_0_2px_rgba(5,217,232,0.15)]"
              autoFocus
              disabled={loading}
            />
          </div>

          {error && (
            <div className="bg-surface border-l-[3px] border-l-accent-pink p-3 rounded-lg">
              <p className="text-sm text-accent-pink">{error}</p>
            </div>
          )}

          <button
            type="submit"
            disabled={loading || !key.trim()}
            className="w-full h-11 text-sm font-semibold bg-accent-pink text-white rounded-lg hover:shadow-[0_0_20px_rgba(255,42,109,0.3)] disabled:opacity-50 disabled:cursor-not-allowed transition-all"
          >
            {loading ? t.loginLoading : t.loginButton}
          </button>
        </form>
      </div>
    </div>
  );
}

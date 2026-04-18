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
      <div className="w-full max-w-sm mx-4">
        <div className="border border-border rounded-lg p-8">
          <h1 className="text-xl font-semibold text-center mb-2">
            {t.loginTitle}
          </h1>
          <p className="text-sm text-muted-foreground text-center mb-6">
            {t.loginSubtitle}
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <input
                type="password"
                value={key}
                onChange={(e) => setKey(e.target.value)}
                placeholder={t.loginKeyPlaceholder}
                className="w-full h-10 px-3 text-sm border border-border rounded bg-transparent focus:outline-none focus:ring-2 focus:ring-primary"
                autoFocus
                disabled={loading}
              />
            </div>

            {error && (
              <div className="rounded bg-destructive/10 border border-destructive/20 p-3">
                <p className="text-sm text-destructive">{error}</p>
              </div>
            )}

            <button
              type="submit"
              disabled={loading || !key.trim()}
              className="w-full h-10 text-sm font-medium bg-primary text-white rounded hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? t.loginLoading : t.loginButton}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

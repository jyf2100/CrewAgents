import { useState, FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  adminApi,
  setAdminKey,
  setAuthMode,
} from "../lib/admin-api";
import { useI18n } from "../hooks/useI18n";

type LoginTab = "user" | "admin" | "email";

export function LoginPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [tab, setTab] = useState<LoginTab>("user");
  const [key, setKey] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);
  const [showRegister, setShowRegister] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    setSuccess("");

    try {
      if (tab === "admin") {
        await adminApi.login(key.trim());
        setAuthMode("admin");
        setAdminKey(key.trim());
      } else if (tab === "user") {
        const res = await adminApi.userLogin(key.trim());
        setAuthMode("user");
        localStorage.setItem("admin_user_token", res.token);
        localStorage.setItem("admin_user_agent_id", String(res.agent_id));
        localStorage.setItem("admin_user_display_name", res.display_name);
      } else {
        // email login
        if (showRegister) {
          await adminApi.register(email.trim(), password, displayName.trim() || undefined);
          setSuccess(t.registerSuccessWaitActivation);
          setShowRegister(false);
          setPassword("");
          return;
        }
        const res = await adminApi.emailLogin(email.trim(), password);
        setAuthMode("email");
        localStorage.setItem("admin_email_token", res.token);
        localStorage.setItem("admin_user_agent_id", String(res.agent_id || ""));
        localStorage.setItem("admin_user_display_name", res.display_name);
      }
      navigate("/", { replace: true });
    } catch (err) {
      if (err instanceof Error) {
        if (err.message.includes("Too many")) {
          setError(t.loginRateLimited);
        } else if (tab === "admin") {
          setError(t.loginFailed);
        } else if (tab === "email" && showRegister) {
          setError(err.message || t.registerFailed);
        } else if (tab === "email") {
          setError(err.message || t.loginFailed);
        } else {
          setError(t.invalidApiKey);
        }
      } else {
        setError(tab === "admin" ? t.loginFailed : tab === "email" ? t.loginFailed : t.invalidApiKey);
      }
    } finally {
      setLoading(false);
    }
  };

  const isAdmin = tab === "admin";
  const isEmail = tab === "email";

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
        <p className="font-[family-name:var(--font-body)] text-text-secondary text-sm text-center mb-6">
          {t.loginSubtitle}
        </p>

        {/* Tab switcher */}
        <div className="flex mb-6 rounded-lg overflow-hidden border border-border">
          <button
            type="button"
            onClick={() => { setTab("email"); setKey(""); setEmail(""); setPassword(""); setError(""); setSuccess(""); setShowRegister(false); }}
            className={`flex-1 py-2 text-sm font-medium transition-colors duration-150 ${
              tab === "email"
                ? "bg-accent-cyan/15 text-accent-cyan border-b-2 border-b-accent-cyan"
                : "bg-surface text-text-secondary hover:text-text-primary"
            }`}
          >
            {t.emailLogin}
          </button>
          <button
            type="button"
            onClick={() => { setTab("user"); setKey(""); setEmail(""); setPassword(""); setError(""); setSuccess(""); setShowRegister(false); }}
            className={`flex-1 py-2 text-sm font-medium transition-colors duration-150 ${
              tab === "user"
                ? "bg-accent-cyan/15 text-accent-cyan border-b-2 border-b-accent-cyan"
                : "bg-surface text-text-secondary hover:text-text-primary"
            }`}
          >
            {t.userLogin}
          </button>
          <button
            type="button"
            onClick={() => { setTab("admin"); setKey(""); setEmail(""); setPassword(""); setError(""); setSuccess(""); setShowRegister(false); }}
            className={`flex-1 py-2 text-sm font-medium transition-colors duration-150 ${
              tab === "admin"
                ? "bg-accent-pink/15 text-accent-pink border-b-2 border-b-accent-pink"
                : "bg-surface text-text-secondary hover:text-text-primary"
            }`}
          >
            {t.adminLogin}
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Admin / API Key login */}
          {!isEmail && (
            <>
              <div>
                <label htmlFor="login-key-input" className="block text-xs text-text-secondary mb-1.5">
                  {isAdmin ? t.adminKey : "API Key"}
                </label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 flex items-center pl-3 pointer-events-none">
                    <svg className="h-4 w-4 text-text-secondary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
                    </svg>
                  </div>
                  <input
                    id="login-key-input"
                    type="password"
                    value={key}
                    onChange={(e) => setKey(e.target.value)}
                    placeholder={isAdmin ? t.loginKeyPlaceholder : t.apiKeyPlaceholder}
                    className="w-full h-11 px-4 pl-10 text-sm bg-background border border-border rounded-lg text-text-primary placeholder:text-text-secondary focus:outline-none focus:border-accent-cyan focus:shadow-[0_0_0_2px_rgba(5,217,232,0.15)]"
                    autoFocus
                    disabled={loading}
                  />
                </div>
              </div>
              {tab === "user" && (
                <p className="text-xs text-text-secondary leading-relaxed">
                  {t.userLoginHint}
                </p>
              )}
            </>
          )}

          {/* Email login / register */}
          {isEmail && (
            <>
              <div>
                <label htmlFor="login-email-input" className="block text-xs text-text-secondary mb-1.5">
                  Email
                </label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 flex items-center pl-3 pointer-events-none">
                    <svg className="h-4 w-4 text-text-secondary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M21.75 6.75v10.5a2.25 2.25 0 01-2.25 2.25h-15a2.25 2.25 0 01-2.25-2.25V6.75m19.5 0A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25m19.5 0v.243a2.25 2.25 0 01-1.07 1.916l-7.5 4.615a2.25 2.25 0 01-2.36 0L3.32 8.91a2.25 2.25 0 01-1.07-1.916V6.75" />
                    </svg>
                  </div>
                  <input
                    id="login-email-input"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder={t.emailPlaceholder}
                    className="w-full h-11 px-4 pl-10 text-sm bg-background border border-border rounded-lg text-text-primary placeholder:text-text-secondary focus:outline-none focus:border-accent-cyan focus:shadow-[0_0_0_2px_rgba(5,217,232,0.15)]"
                    autoFocus
                    disabled={loading}
                  />
                </div>
              </div>
              <div>
                <label htmlFor="login-password-input" className="block text-xs text-text-secondary mb-1.5">
                  {t.passwordLabel}
                </label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 flex items-center pl-3 pointer-events-none">
                    <svg className="h-4 w-4 text-text-secondary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
                    </svg>
                  </div>
                  <input
                    id="login-password-input"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder={t.passwordPlaceholder}
                    className="w-full h-11 px-4 pl-10 text-sm bg-background border border-border rounded-lg text-text-primary placeholder:text-text-secondary focus:outline-none focus:border-accent-cyan focus:shadow-[0_0_0_2px_rgba(5,217,232,0.15)]"
                    disabled={loading}
                  />
                </div>
              </div>
              {showRegister && (
                <div>
                  <label htmlFor="register-name-input" className="block text-xs text-text-secondary mb-1.5">
                    {t.displayName}
                  </label>
                  <input
                    id="register-name-input"
                    type="text"
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    placeholder={t.displayNamePlaceholder}
                    className="w-full h-11 px-4 text-sm bg-background border border-border rounded-lg text-text-primary placeholder:text-text-secondary focus:outline-none focus:border-accent-cyan focus:shadow-[0_0_0_2px_rgba(5,217,232,0.15)]"
                    disabled={loading}
                  />
                </div>
              )}
              <button
                type="button"
                onClick={() => { setShowRegister(!showRegister); setError(""); setSuccess(""); }}
                className="text-xs text-accent-cyan hover:underline"
              >
                {showRegister ? t.backToLogin : t.registerButton}
              </button>
            </>
          )}

          {success && (
            <div className="bg-surface border-l-[3px] border-l-green-400 p-3 rounded-lg">
              <p className="text-sm text-green-400">{success}</p>
            </div>
          )}

          {error && (
            <div className="bg-surface border-l-[3px] border-l-accent-pink p-3 rounded-lg">
              <p className="text-sm text-accent-pink">{error}</p>
            </div>
          )}

          <button
            type="submit"
            disabled={loading || (isEmail ? !email.trim() || !password.trim() : !key.trim())}
            className={`w-full h-11 text-sm font-semibold rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-all ${
              isAdmin
                ? "bg-accent-pink text-white hover:shadow-[0_0_20px_rgba(255,42,109,0.3)]"
                : "bg-accent-cyan text-background hover:shadow-[0_0_20px_rgba(5,217,232,0.3)]"
            }`}
          >
            {loading ? t.loginLoading : (showRegister ? t.registerButton : t.loginButton)}
          </button>
        </form>
      </div>
    </div>
  );
}

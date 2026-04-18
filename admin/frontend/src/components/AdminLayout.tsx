import { Outlet, Navigate, useLocation, Link } from "react-router-dom";
import { useI18n } from "../hooks/useI18n";

export function AdminLayout() {
  const { t, lang, setLang } = useI18n();
  const location = useLocation();
  const key = localStorage.getItem("admin_api_key");

  if (!key) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Header */}
      <header className="border-b border-border bg-background/95 backdrop-blur sticky top-0 z-40">
        <div className="mx-auto max-w-7xl flex h-14 items-center justify-between px-4">
          {/* Left: Title + Nav */}
          <div className="flex items-center gap-6">
            <Link to="/" className="text-lg font-semibold">
              {t.headerTitle}
            </Link>
            <nav className="flex items-center gap-4 text-sm">
              <Link
                to="/"
                className={
                  location.pathname === "/"
                    ? "text-primary font-medium"
                    : "text-muted-foreground hover:text-foreground"
                }
              >
                {t.navDashboard}
              </Link>
              <Link
                to="/settings"
                className={
                  location.pathname === "/settings"
                    ? "text-primary font-medium"
                    : "text-muted-foreground hover:text-foreground"
                }
              >
                {t.navSettings}
              </Link>
            </nav>
          </div>

          {/* Right: Language switcher */}
          <div className="flex items-center gap-3">
            <button
              onClick={() => setLang(lang === "zh" ? "en" : "zh")}
              className="h-8 px-3 text-xs border border-border hover:bg-accent rounded"
            >
              {t.languageSwitch}
            </button>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="mx-auto max-w-7xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}

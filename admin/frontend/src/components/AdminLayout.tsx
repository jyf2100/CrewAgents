import { useState, useCallback } from "react";
import { Outlet, Navigate, useLocation, Link } from "react-router-dom";
import { useI18n } from "../hooks/useI18n";

/* ── Inline icon components (no external deps) ── */

function IconDashboard({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </svg>
  );
}

function IconSettings({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function IconMenu({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <line x1="4" y1="6" x2="20" y2="6" />
      <line x1="4" y1="12" x2="20" y2="12" />
      <line x1="4" y1="18" x2="20" y2="18" />
    </svg>
  );
}

function IconX({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

function IconLogout({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <polyline points="16 17 21 12 16 7" />
      <line x1="21" y1="12" x2="9" y2="12" />
    </svg>
  );
}

/* ── Navigation items ── */

interface NavItem {
  to: string;
  label: string;
  icon: typeof IconDashboard;
}

/* ── Component ── */

export function AdminLayout() {
  const { t, lang, setLang } = useI18n();
  const location = useLocation();
  const key = localStorage.getItem("admin_api_key");

  const [drawerOpen, setDrawerOpen] = useState(false);
  const closeDrawer = useCallback(() => setDrawerOpen(false), []);

  /* Auth guard */
  if (!key) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  const navItems: NavItem[] = [
    { to: "/", label: t.navDashboard, icon: IconDashboard },
    { to: "/settings", label: t.navSettings, icon: IconSettings },
  ];

  const isActive = (path: string) =>
    path === "/" ? location.pathname === "/" : location.pathname.startsWith(path);

  function handleLogout() {
    localStorage.removeItem("admin_api_key");
    window.location.href = "/login";
  }

  /* ── Sidebar content (shared between desktop and mobile drawer) ── */
  function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
    return (
      <div className="flex flex-col h-full">
        {/* Brand */}
        <div className="px-5 py-5 shrink-0">
          <h1 className="glow-pink-text font-[family-name:var(--font-display)] text-lg font-bold tracking-[0.15em] text-accent-pink">
            HERMES
          </h1>
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-2 mt-2 space-y-1" aria-label="Main navigation">
          {navItems.map((item) => {
            const active = isActive(item.to);
            const Icon = item.icon;
            return (
              <Link
                key={item.to}
                to={item.to}
                onClick={onNavigate}
                className={[
                  "flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-colors duration-150 relative",
                  active
                    ? "text-text-primary font-medium"
                    : "text-text-secondary hover:text-text-primary hover:bg-surface/50",
                ].join(" ")}
                aria-current={active ? "page" : undefined}
              >
                {active && (
                  <span
                    className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r-full bg-accent-pink"
                    aria-hidden="true"
                  />
                )}
                <Icon className="w-4 h-4 shrink-0" />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>

        {/* Bottom section */}
        <div className="px-3 pb-4 space-y-3 shrink-0">
          {/* Cluster status placeholder */}
          <div className="px-3 py-2.5 rounded-md border border-border-subtle bg-surface/30">
            <p className="text-xs text-text-secondary font-[family-name:var(--font-mono)]">
              {t.clusterStatus}
            </p>
          </div>

          {/* Language toggle */}
          <button
            onClick={() => setLang(lang === "zh" ? "en" : "zh")}
            className="w-full flex items-center justify-center h-8 px-3 text-xs rounded-full border border-accent-cyan text-accent-cyan transition-colors duration-150 hover:bg-accent-cyan/10"
          >
            {t.languageSwitch}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen h-screen flex bg-background text-text-primary overflow-hidden">
      {/* ── Desktop sidebar ── */}
      <aside
        className="hidden md:flex md:flex-col md:w-56 shrink-0 bg-sidebar-bg border-l border-accent-pink/20"
        aria-label="Sidebar navigation"
      >
        <SidebarContent />
      </aside>

      {/* ── Mobile drawer backdrop ── */}
      {drawerOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 md:hidden"
          onClick={closeDrawer}
          aria-hidden="true"
        />
      )}

      {/* ── Mobile sidebar drawer ── */}
      <aside
        className={[
          "fixed inset-y-0 left-0 z-50 w-56 bg-sidebar-bg border-r border-accent-pink/20 md:hidden transition-transform duration-300 ease-out",
          drawerOpen ? "translate-x-0" : "-translate-x-full",
        ].join(" ")}
        aria-label="Mobile navigation"
        aria-hidden={!drawerOpen}
      >
        {/* Close button */}
        <div className="absolute top-3 right-3">
          <button
            onClick={closeDrawer}
            className="p-1.5 rounded-md text-text-secondary hover:text-text-primary hover:bg-surface/50 transition-colors"
            aria-label="Close navigation menu"
          >
            <IconX className="w-4 h-4" />
          </button>
        </div>
        <SidebarContent onNavigate={closeDrawer} />
      </aside>

      {/* ── Main area ── */}
      <div className="flex flex-col flex-1 min-w-0">
        {/* Topbar */}
        <header className="glass h-14 shrink-0 flex items-center justify-between px-4 border-b border-border-subtle z-30">
          {/* Left: mobile hamburger */}
          <button
            onClick={() => setDrawerOpen(true)}
            className="md:hidden p-2 -ml-2 rounded-md text-text-secondary hover:text-text-primary hover:bg-surface/50 transition-colors"
            aria-label="Open navigation menu"
          >
            <IconMenu className="w-5 h-5" />
          </button>

          {/* Spacer to push logout right on desktop */}
          <div className="hidden md:block" />

          {/* Right: logout */}
          <button
            onClick={handleLogout}
            className="flex items-center gap-2 px-3 py-1.5 rounded-md text-sm text-text-secondary hover:text-text-primary hover:bg-surface/50 transition-colors"
          >
            <IconLogout className="w-4 h-4" />
            <span className="hidden sm:inline">Logout</span>
          </button>
        </header>

        {/* Content */}
        <main className="flex-1 min-h-0 overflow-auto">
          <div className="p-4 md:p-6 max-w-7xl mx-auto w-full animate-page-enter">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}

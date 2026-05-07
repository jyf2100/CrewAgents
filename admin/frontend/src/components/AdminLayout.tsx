import { useState, useCallback } from "react";
import { Outlet, Navigate, useLocation, Link, NavLink } from "react-router-dom";
import { useI18n } from "../hooks/useI18n";
import { getAuthMode, adminApi } from "../lib/admin-api";
import { AdminApiError } from "../lib/admin-api";

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
  const authMode = getAuthMode();
  const isUser = authMode === "user" || authMode === "email";

  // Auth check: user/email mode uses token, admin mode uses key
  const adminKey = localStorage.getItem("admin_api_key");
  const userToken = localStorage.getItem("admin_user_token") || localStorage.getItem("admin_email_token");
  const isAuthenticated = isUser ? !!userToken : !!adminKey;

  const [drawerOpen, setDrawerOpen] = useState(false);
  const closeDrawer = useCallback(() => setDrawerOpen(false), []);

  /* Auth guard */
  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  const navItems: NavItem[] = isUser
    ? [{ to: "/", label: t.navDashboard, icon: IconDashboard }]
    : [
        { to: "/", label: t.navDashboard, icon: IconDashboard },
        { to: "/settings", label: t.navSettings, icon: IconSettings },
      ];

  const isActive = (path: string) =>
    path === "/" ? location.pathname === "/" : location.pathname.startsWith(path);

  async function handleLogout() {
    if (isUser) {
      await adminApi.userLogout();
      localStorage.removeItem("admin_user_token");
      localStorage.removeItem("admin_email_token");
      localStorage.removeItem("admin_user_agent_id");
      localStorage.removeItem("admin_user_display_name");
    } else {
      localStorage.removeItem("admin_api_key");
    }
    localStorage.removeItem("admin_mode");
    window.location.href = "/admin/";
  }

  // In user mode, redirect /settings and /create to /
  if (isUser) {
    if (location.pathname === "/settings" || location.pathname === "/create") {
      return <Navigate to="/" replace />;
    }
  }

  const userDisplayName = localStorage.getItem("admin_user_display_name") || "";

  /* ── Sidebar content (shared between desktop and mobile drawer) ── */
  function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
    return (
      <div className="flex flex-col h-full">
        {/* Brand */}
        <div className="px-5 py-5 shrink-0">
          <h1 className="glow-pink-text font-[family-name:var(--font-display)] text-lg font-bold tracking-[0.15em] text-accent-pink">
            NEWHERMES
          </h1>
          {isUser && userDisplayName && (
            <p className="mt-1 text-xs text-text-secondary truncate" title={userDisplayName}>
              {userDisplayName}
            </p>
          )}
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

        {/* Web UI / Start Chat link */}
        <div className="px-2 mt-4">
          {isUser ? (
            <Link
              to="/chat"
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-sm text-accent-cyan hover:bg-accent-cyan/10 transition-colors duration-150 border border-accent-cyan/30"
            >
              <svg viewBox="0 0 24 24" className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.087.16 2.185.283 3.293.369V21l4.076-4.076a1.526 1.526 0 011.037-.443 48.282 48.282 0 005.68-.494c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
              </svg>
              <span>{t.startChat}</span>
            </Link>
          ) : (
            <a
              href={window.location.origin}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-3 px-3 py-2.5 rounded-md text-sm text-text-secondary hover:text-text-primary hover:bg-surface/50 transition-colors duration-150"
            >
              <svg viewBox="0 0 24 24" className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.087.16 2.185.283 3.293.369V21l4.076-4.076a1.526 1.526 0 011.037-.443 48.282 48.282 0 005.68-.494c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
              </svg>
              <span>{t.navWebui}</span>
              <svg viewBox="0 0 20 20" className="w-3 h-3 ml-auto opacity-40" fill="currentColor" aria-hidden="true">
                <path d="M11 3a1 1 0 100 2h2.586l-6.293 6.293a1 1 0 101.414 1.414L15 6.414V9a1 1 0 102 0V4a1 1 0 00-1-1h-5z" />
                <path d="M5 5a2 2 0 00-2 2v8a2 2 0 002 2h8a2 2 0 002-2v-3a1 1 0 10-2 0v3H5V7h3a1 1 0 000-2H5z" />
              </svg>
            </a>
          )}
        </div>

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

        {/* Swarm section — admin only */}
        {!isUser && (
          <div className="px-2 mt-4">
            <div className="px-3 py-2 text-xs uppercase text-text-secondary tracking-wider">
              {t.navSwarm}
            </div>
            <NavLink
              to="/swarm"
              onClick={onNavigate}
              className={({ isActive }) =>
                [
                  "flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-colors duration-150 relative",
                  isActive
                    ? "text-text-primary font-medium"
                    : "text-text-secondary hover:text-text-primary hover:bg-surface/50",
                ].join(" ")
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <span
                      className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r-full bg-accent-pink"
                      aria-hidden="true"
                    />
                  )}
                  <svg
                    viewBox="0 0 24 24"
                    className="w-4 h-4 shrink-0"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    aria-hidden="true"
                  >
                    <circle cx="12" cy="5" r="2.5" />
                    <circle cx="5" cy="14" r="2.5" />
                    <circle cx="19" cy="14" r="2.5" />
                    <circle cx="8" cy="20" r="2.5" />
                    <circle cx="16" cy="20" r="2.5" />
                    <line x1="12" y1="7.5" x2="5" y2="11.5" />
                    <line x1="12" y1="7.5" x2="19" y2="11.5" />
                    <line x1="5" y1="14" x2="8" y2="17.5" />
                    <line x1="19" y1="14" x2="16" y2="17.5" />
                    <line x1="8" y1="20" x2="16" y2="20" />
                  </svg>
                  <span>{t.navSwarm}</span>
                </>
              )}
            </NavLink>
            <NavLink
              to="/swarm/tasks"
              onClick={onNavigate}
              className={({ isActive }) =>
                [
                  "flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-colors duration-150 relative",
                  isActive
                    ? "text-text-primary font-medium"
                    : "text-text-secondary hover:text-text-primary hover:bg-surface/50",
                ].join(" ")
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <span
                      className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r-full bg-accent-pink"
                      aria-hidden="true"
                    />
                  )}
                  <svg
                    viewBox="0 0 24 24"
                    className="w-4 h-4 shrink-0"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    aria-hidden="true"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25zM6.75 12h.008v.008H6.75V12zm0 3h.008v.008H6.75V15zm0 3h.008v.008H6.75V18z" />
                  </svg>
                  <span>{t.navTasks}</span>
                </>
              )}
            </NavLink>
            <NavLink
              to="/swarm/knowledge"
              onClick={onNavigate}
              className={({ isActive }) =>
                [
                  "flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-colors duration-150 relative",
                  isActive
                    ? "text-text-primary font-medium"
                    : "text-text-secondary hover:text-text-primary hover:bg-surface/50",
                ].join(" ")
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <span
                      className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r-full bg-accent-pink"
                      aria-hidden="true"
                    />
                  )}
                  <svg
                    viewBox="0 0 24 24"
                    className="w-4 h-4 shrink-0"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    aria-hidden="true"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" />
                  </svg>
                  <span>{t.navKnowledge}</span>
                </>
              )}
            </NavLink>
            <NavLink
              to="/swarm/crews"
              onClick={onNavigate}
              className={({ isActive }) =>
                [
                  "flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-colors duration-150 relative",
                  isActive
                    ? "text-text-primary font-medium"
                    : "text-text-secondary hover:text-text-primary hover:bg-surface/50",
                ].join(" ")
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <span
                      className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r-full bg-accent-pink"
                      aria-hidden="true"
                    />
                  )}
                  <svg
                    viewBox="0 0 24 24"
                    className="w-4 h-4 shrink-0"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    aria-hidden="true"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" />
                  </svg>
                  <span>{t.navCrews}</span>
                </>
              )}
            </NavLink>
          </div>
        )}

        {/* Orchestrator section — admin only */}
        {!isUser && (
          <div className="mt-6 px-3">
            <p className="text-xs font-medium text-text-muted uppercase tracking-wider mb-2 px-2">
              {t.orchestratorNav}
            </p>
            <NavLink
              to="/orchestrator"
              onClick={onNavigate}
              className={({ isActive }) =>
                [
                  "flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-colors duration-150 relative",
                  isActive
                    ? "text-text-primary font-medium"
                    : "text-text-secondary hover:text-text-primary hover:bg-surface/50",
                ].join(" ")
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <span
                      className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r-full bg-accent-pink"
                      aria-hidden="true"
                    />
                  )}
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    className="w-4 h-4 shrink-0"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <path d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
                  </svg>
                  <span>{t.orchestratorOverview}</span>
                </>
              )}
            </NavLink>
            <NavLink
              to="/orchestrator/tasks/new"
              onClick={onNavigate}
              className={({ isActive }) =>
                [
                  "flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-colors duration-150 relative",
                  isActive
                    ? "text-text-primary font-medium"
                    : "text-text-secondary hover:text-text-primary hover:bg-surface/50",
                ].join(" ")
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <span
                      className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r-full bg-accent-pink"
                      aria-hidden="true"
                    />
                  )}
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    className="w-4 h-4 shrink-0"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <path d="M12 4v16m8-8H4" />
                  </svg>
                  <span>{t.orchestratorNewTask}</span>
                </>
              )}
            </NavLink>
          </div>
        )}

        {/* Bottom section */}
        <div className="px-3 pb-4 space-y-3 shrink-0">
          {/* User mode badge */}
          {isUser && (
            <div className="px-3 py-2.5 rounded-md border border-accent-cyan/30 bg-accent-cyan/5">
              <p className="text-xs text-accent-cyan font-medium">
                {t.userMode}
              </p>
            </div>
          )}

          {/* Cluster status placeholder — admin only */}
          {!isUser && (
            <div className="px-3 py-2.5 rounded-md border border-border-subtle bg-surface/30">
              <p className="text-xs text-text-secondary font-[family-name:var(--font-mono)]">
                {t.clusterStatus}
              </p>
            </div>
          )}

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

          {/* User display name in topbar for user mode */}
          {isUser && userDisplayName && (
            <span className="hidden md:inline text-sm text-text-secondary">
              {userDisplayName}
            </span>
          )}

          {/* Spacer to push logout right on desktop */}
          <div className="hidden md:block" />

          {/* Right: logout */}
          <button
            onClick={handleLogout}
            className="flex items-center gap-2 px-3 py-1.5 rounded-md text-sm text-text-secondary hover:text-text-primary hover:bg-surface/50 transition-colors"
          >
            <IconLogout className="w-4 h-4" />
            <span className="hidden sm:inline">{t.logout}</span>
          </button>
        </header>

        {/* Content */}
        <main className="flex-1 min-h-0 overflow-auto relative">
          <div className="p-4 md:p-6 max-w-7xl mx-auto w-full animate-page-enter">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import { Navigate, Outlet } from "react-router-dom";
import { adminApi } from "../lib/admin-api";

export function OrchestratorGuard() {
  const [enabled, setEnabled] = useState<boolean | null>(null);

  useEffect(() => {
    adminApi.orchestratorCapability()
      .then(({ enabled }) => setEnabled(enabled))
      .catch(() => setEnabled(false));
  }, []);

  if (enabled === null) return null;
  if (!enabled) return <Navigate to="/admin/" replace />;
  return <Outlet />;
}

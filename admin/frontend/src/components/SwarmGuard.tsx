import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { adminFetch } from "../lib/admin-api";

export function SwarmGuard({ children }: { children: React.ReactNode }) {
  const [enabled, setEnabled] = useState<boolean | null>(null);

  useEffect(() => {
    // adminFetch<T> returns parsed JSON directly (not a Response)
    adminFetch<{ enabled: boolean }>("/swarm/capability")
      .then((d) => setEnabled(d.enabled))
      .catch(() => setEnabled(false));
  }, []);

  if (enabled === null) return null;
  if (!enabled) return <Navigate to="/" replace />;
  return <>{children}</>;
}

import { BrowserRouter, Routes, Route, Outlet } from "react-router-dom";
import { AdminLayout } from "./components/AdminLayout";
import { DashboardPage } from "./pages/DashboardPage";
import { AgentDetailPage } from "./pages/AgentDetailPage";
import { CreateAgentPage } from "./pages/CreateAgentPage";
import { SettingsPage } from "./pages/SettingsPage";
import { LoginPage } from "./pages/LoginPage";
import { SwarmGuard } from "./components/SwarmGuard";
import { SwarmOverviewPage } from "./pages/swarm/SwarmOverviewPage";
import { setAdminKey } from "./lib/admin-api";
import { useEffect } from "react";

function App() {
  useEffect(() => {
    const key = localStorage.getItem("admin_api_key");
    if (key) setAdminKey(key);
  }, []);

  return (
    <BrowserRouter basename="/admin">
      <Routes>
        <Route element={<AdminLayout />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/agents/:id" element={<AgentDetailPage />} />
          <Route path="/create" element={<CreateAgentPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route
            element={
              <SwarmGuard>
                <Outlet />
              </SwarmGuard>
            }
          >
            <Route path="/swarm" element={<SwarmOverviewPage />} />
          </Route>
        </Route>
        <Route path="/login" element={<LoginPage />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;

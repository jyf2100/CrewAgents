import { BrowserRouter, Routes, Route, Outlet } from "react-router-dom";
import { AdminLayout } from "./components/AdminLayout";
import { DashboardPage } from "./pages/DashboardPage";
import { AgentDetailPage } from "./pages/AgentDetailPage";
import { CreateAgentPage } from "./pages/CreateAgentPage";
import { SettingsPage } from "./pages/SettingsPage";
import { LoginPage } from "./pages/LoginPage";
import { SwarmGuard } from "./components/SwarmGuard";
import { SwarmOverviewPage } from "./pages/swarm/SwarmOverviewPage";
import { CrewListPage } from "./pages/swarm/CrewListPage";
import { CrewEditPage } from "./pages/swarm/CrewEditPage";
import { ComingSoonPage } from "./pages/swarm/ComingSoonPage";
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
            <Route path="/swarm/tasks" element={<ComingSoonPage title="Tasks" />} />
            <Route path="/swarm/knowledge" element={<ComingSoonPage title="Knowledge" />} />
            <Route path="/swarm/crews" element={<CrewListPage />} />
            <Route path="/swarm/crews/new" element={<CrewEditPage />} />
            <Route path="/swarm/crews/:id/edit" element={<CrewEditPage />} />
          </Route>
        </Route>
        <Route path="/login" element={<LoginPage />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;

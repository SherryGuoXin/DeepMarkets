import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { OverviewPage } from "./pages/OverviewPage";
import { InstitutionsPage } from "./pages/InstitutionsPage";
import { InstitutionPage } from "./pages/InstitutionPage";
import { SecuritiesPage } from "./pages/SecuritiesPage";
import { SecurityPage } from "./pages/SecurityPage";
import { RelationshipPage } from "./pages/RelationshipPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<OverviewPage />} />
        <Route path="institutions" element={<InstitutionsPage />} />
        <Route path="institutions/:cik" element={<InstitutionPage />} />
        <Route path="securities" element={<SecuritiesPage />} />
        <Route path="securities/:cusip" element={<SecurityPage />} />
        <Route path="relationships/:cik/:cusip" element={<RelationshipPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import LandingPage from './pages/LandingPage.jsx';

const DashboardPage = lazy(() => import('./pages/DashboardPage.jsx'));

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route
        path="/dashboard"
        element={(
          <Suspense fallback={<main className="dashboard-loading">Loading dashboard…</main>}>
            <DashboardPage />
          </Suspense>
        )}
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

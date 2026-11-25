import { Link, Route, Routes } from 'react-router-dom';
import DailyPage from './pages/DailyPage';
import GazettePage from './pages/GazettePage';
import LoginPage from './pages/LoginPage';
import RunsPage from './pages/RunsPage';
import SearchPage from './pages/SearchPage';
import SourcesPage from './pages/SourcesPage';

// Opt in to the v7 behaviour now (silences the v6 future-flag warnings).
export const ROUTER_FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true } as const;

function NotFound() {
  return (
    <div className="page">
      <h2 className="page-title">Page not found</h2>
      <p>
        <Link to="/">Back to the gazette</Link>
      </p>
    </div>
  );
}

export default function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<GazettePage />} />
      <Route path="/daily" element={<DailyPage />} />
      <Route path="/daily/:day" element={<DailyPage />} />
      <Route path="/runs" element={<RunsPage />} />
      <Route path="/sources" element={<SourcesPage />} />
      <Route path="/search" element={<SearchPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}

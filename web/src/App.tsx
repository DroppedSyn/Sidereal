import { NavLink, useLocation } from 'react-router-dom';
import LastRun from './components/LastRun';
import UserMenu from './components/UserMenu';
import { useAuthRedirect } from './lib/useAuthRedirect';
import AppRoutes from './routes';

const TABS = [
  { to: '/', label: 'Gazette', end: true },
  { to: '/daily', label: 'Daily', end: false },
  { to: '/runs', label: 'Runs', end: false },
  { to: '/sources', label: 'Sources', end: false },
];

export default function App() {
  useAuthRedirect();
  const onLogin = useLocation().pathname === '/login';
  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-inner">
          <h1 className="masthead">Sidereal</h1>
          {!onLogin && (
            <>
              <nav className="tabs" aria-label="Main">
                {TABS.map((t) => (
                  <NavLink key={t.to} to={t.to} end={t.end} className="tab">
                    {t.label}
                  </NavLink>
                ))}
              </nav>
              <LastRun />
              <UserMenu />
            </>
          )}
        </div>
      </header>
      <main className="content">
        <AppRoutes />
      </main>
    </div>
  );
}

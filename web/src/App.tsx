import { useRef } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import LastRun from './components/LastRun';
import SearchBox from './components/SearchBox';
import UserMenu from './components/UserMenu';
import { useAuthRedirect } from './lib/useAuthRedirect';
import { useStickyHeight } from './lib/useStickyHeight';
import AppRoutes from './routes';

const TABS = [
  { to: '/', label: 'Gazette', end: true },
  { to: '/daily', label: 'Daily', end: false },
  { to: '/week', label: 'Week', end: false },
  { to: '/runs', label: 'Runs', end: false },
  { to: '/sources', label: 'Sources', end: false },
  { to: '/settings', label: 'Settings', end: false },
];

export default function App() {
  useAuthRedirect();
  const topbar = useRef<HTMLElement>(null);
  useStickyHeight(topbar);
  const onLogin = useLocation().pathname === '/login';
  return (
    <div className="app">
      <header className="topbar" ref={topbar}>
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
              <SearchBox />
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

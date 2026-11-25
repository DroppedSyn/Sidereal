// Registers the API client's 401 handler: go to /login?next=<where we were> (plan §11.2).
import { useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { setUnauthorizedHandler } from '../api/client';
import { loginPath } from './next';

export function useAuthRedirect(): void {
  const navigate = useNavigate();
  const location = useLocation();
  const here = useRef('/');
  here.current = location.pathname + location.search;

  useEffect(() => {
    setUnauthorizedHandler(() => {
      if (here.current === '/login' || here.current.startsWith('/login?')) return;
      navigate(loginPath(here.current), { replace: true });
    });
    return () => setUnauthorizedHandler(null);
  }, [navigate]);
}

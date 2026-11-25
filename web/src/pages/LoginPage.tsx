// Login (plan §11.2): username, password and an optional TOTP code; one generic error.
import { useQueryClient } from '@tanstack/react-query';
import { type FormEvent, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ApiError } from '../api/client';
import { useLogin } from '../api/hooks';
import { safeNext } from '../lib/next';

function failure(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Invalid username, password or code.';
    if (error.status === 429) return 'Too many failed attempts. Try again in 15 minutes.';
    if (error.status === 404) return 'Login is not needed: authentication is off.';
    if (error.status === 0) return error.message;
  }
  return 'Login failed. Please try again.';
}

export default function LoginPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const client = useQueryClient();
  const login = useLogin();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');

  function submit(event: FormEvent) {
    event.preventDefault();
    const trimmed = code.trim();
    login.mutate(
      { username, password, code: trimmed === '' ? null : trimmed },
      {
        onSuccess: () => {
          void client.resetQueries();
          navigate(safeNext(params.get('next')), { replace: true });
        },
        onError: () => {
          setPassword('');
          setCode('');
        },
      },
    );
  }

  return (
    <div className="page login">
      <h2 className="page-title">Sign in</h2>
      <form className="login-form" onSubmit={submit}>
        <label className="field">
          <span>Username</span>
          <input name="username" autoComplete="username" required value={username}
            onChange={(e) => setUsername(e.target.value)} />
        </label>
        <label className="field">
          <span>Password</span>
          <input name="password" type="password" autoComplete="current-password" required
            value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        <label className="field">
          <span>Authentication code (if set up)</span>
          <input name="code" inputMode="numeric" autoComplete="one-time-code" maxLength={8}
            value={code} onChange={(e) => setCode(e.target.value)} />
        </label>
        <button type="submit" className="button" disabled={login.isPending}>
          {login.isPending ? 'Signing in…' : 'Sign in'}
        </button>
        <p role="alert" className="status-error">
          {login.isError ? failure(login.error) : ''}
        </p>
      </form>
    </div>
  );
}

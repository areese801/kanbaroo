import { useState, type FormEvent, type JSX } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { apiFetch } from '../api/client';
import { useAuthStore } from '../state/auth';

type LocationState = { from?: string };

export default function Login(): JSX.Element {
  const navigate = useNavigate();
  const location = useLocation();
  const setToken = useAuthStore((s) => s.setToken);
  const clearToken = useAuthStore((s) => s.clearToken);
  const [value, setValue] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const candidate = value.trim();
    if (!candidate) {
      setError('Enter an API token to continue.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const response = await apiFetch('/api/v1/workspaces', {
        method: 'GET',
        token: candidate,
      });
      if (response.ok) {
        setToken(candidate);
        const state = location.state as LocationState | null;
        const target = state?.from ?? '/';
        navigate(target, { replace: true });
        return;
      }
      clearToken();
      if (response.status === 401) {
        setError('That token was rejected. Check the value and try again.');
      } else {
        setError(`Sign-in failed (status ${response.status}). Try again in a moment.`);
      }
    } catch (cause) {
      clearToken();
      setError('Could not reach the server. Check your connection and retry.');
      console.error('Login request failed', cause);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="app-shell">
      <main className="panel">
        <h1>Kanberoo</h1>
        <p className="subtitle">Sign in with an API token.</p>
        <form onSubmit={handleSubmit} noValidate>
          <div className="form-row">
            <label htmlFor="token">API token</label>
            <input
              id="token"
              type="password"
              name="token"
              value={value}
              autoComplete="off"
              autoFocus
              spellCheck={false}
              onChange={(event) => setValue(event.target.value)}
              placeholder="kbr_..."
              aria-invalid={error !== null}
              aria-describedby={error !== null ? 'login-error' : undefined}
            />
          </div>
          {error !== null ? (
            <p id="login-error" role="alert" className="error-text">
              {error}
            </p>
          ) : null}
          <button type="submit" disabled={submitting}>
            {submitting ? 'Signing in...' : 'Sign in'}
          </button>
        </form>
        <p className="muted">
          Tokens are created with <code>kb token create</code> or via the REST API.
        </p>
      </main>
    </div>
  );
}

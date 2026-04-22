import type { JSX } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../state/auth';

export default function Home(): JSX.Element {
  const navigate = useNavigate();
  const clearToken = useAuthStore((s) => s.clearToken);

  function handleLogout(): void {
    clearToken();
    navigate('/login', { replace: true });
  }

  return (
    <div className="app-shell">
      <main className="panel">
        <h1>Kanberoo</h1>
        <p className="subtitle">Logged in. Board lands in milestone M3.</p>
        <button type="button" onClick={handleLogout}>
          Log out
        </button>
      </main>
    </div>
  );
}

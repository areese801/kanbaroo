import type { JSX } from 'react';
import { Link, Outlet, useNavigate, useParams } from 'react-router-dom';
import { useAuthStore } from '../state/auth';
import { useWorkspace } from '../queries/workspaces';

function WorkspaceBreadcrumb(): JSX.Element | null {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const query = useWorkspace(workspaceId);
  if (!workspaceId) {
    return null;
  }
  const label = query.data ? `${query.data.name} (${query.data.key})` : 'Loading...';
  return (
    <span className="breadcrumb">
      <span className="breadcrumb-sep">/</span>
      <span className="breadcrumb-item">{label}</span>
    </span>
  );
}

export default function AppHeader(): JSX.Element {
  const navigate = useNavigate();
  const clearToken = useAuthStore((s) => s.clearToken);

  function handleLogout(): void {
    clearToken();
    navigate('/login', { replace: true });
  }

  return (
    <div className="app-frame">
      <header className="app-header">
        <div className="app-header-left">
          <Link to="/workspaces" className="app-title">
            Kanberoo
          </Link>
          <WorkspaceBreadcrumb />
        </div>
        <button type="button" className="secondary" onClick={handleLogout}>
          Log out
        </button>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}

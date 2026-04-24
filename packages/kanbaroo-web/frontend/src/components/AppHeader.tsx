import { useCallback, useState, type JSX } from 'react';
import { Link, Outlet, useMatch, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../state/auth';
import { useStory } from '../queries/stories';
import { useWorkspace } from '../queries/workspaces';
import { useHotkey } from '../hooks/useHotkey';
import KeyboardHelpModal from './KeyboardHelpModal';

function WorkspaceCrumb({ workspaceId }: { workspaceId: string }): JSX.Element {
  const query = useWorkspace(workspaceId);
  const label = query.data ? `${query.data.name} (${query.data.key})` : 'Loading...';
  return (
    <span className="breadcrumb">
      <span className="breadcrumb-sep">/</span>
      <Link to={`/workspaces/${encodeURIComponent(workspaceId)}/board`} className="breadcrumb-item">
        {label}
      </Link>
    </span>
  );
}

function StoryCrumb({ storyId }: { storyId: string }): JSX.Element {
  const storyQuery = useStory(storyId);
  const story = storyQuery.data ?? null;
  const label = story ? story.human_id : 'Loading...';
  return (
    <>
      {story ? <WorkspaceCrumb workspaceId={story.workspace_id} /> : null}
      <span className="breadcrumb">
        <span className="breadcrumb-sep">/</span>
        <span className="breadcrumb-item">{label}</span>
      </span>
    </>
  );
}

function Breadcrumbs(): JSX.Element | null {
  const boardMatch = useMatch('/workspaces/:workspaceId/board');
  const storyMatch = useMatch('/stories/:storyId');

  if (storyMatch?.params.storyId) {
    return <StoryCrumb storyId={storyMatch.params.storyId} />;
  }
  if (boardMatch?.params.workspaceId) {
    return <WorkspaceCrumb workspaceId={boardMatch.params.workspaceId} />;
  }
  return null;
}

export default function AppHeader(): JSX.Element {
  const navigate = useNavigate();
  const clearToken = useAuthStore((s) => s.clearToken);
  const [helpOpen, setHelpOpen] = useState(false);

  const handleLogout = (): void => {
    clearToken();
    navigate('/login', { replace: true });
  };

  const toggleHelp = useCallback(() => {
    setHelpOpen((open) => !open);
  }, []);

  useHotkey('?', toggleHelp);

  return (
    <div className="app-frame">
      <header className="app-header">
        <div className="app-header-left">
          <Link to="/workspaces" className="app-title">
            Kanbaroo
          </Link>
          <Breadcrumbs />
        </div>
        <div className="app-header-actions">
          <button
            type="button"
            className="secondary icon-button"
            aria-label="Keyboard shortcuts"
            title="Keyboard shortcuts (?)"
            onClick={() => setHelpOpen(true)}
          >
            ?
          </button>
          <button type="button" className="secondary" onClick={handleLogout}>
            Log out
          </button>
        </div>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
      {helpOpen ? <KeyboardHelpModal onClose={() => setHelpOpen(false)} /> : null}
    </div>
  );
}

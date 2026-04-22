import { useEffect, type JSX, type ReactNode } from 'react';
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { setUnauthorizedHandler } from './api/client';
import { useAuthStore } from './state/auth';
import AppHeader from './components/AppHeader';
import Board from './routes/Board';
import Login from './routes/Login';
import StoryDetail from './routes/StoryDetail';
import WorkspaceList from './routes/WorkspaceList';

type RequireAuthProps = { children: ReactNode };

function RequireAuth({ children }: RequireAuthProps): JSX.Element {
  const token = useAuthStore((s) => s.token);
  const location = useLocation();
  if (!token) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}

export default function App(): JSX.Element {
  const navigate = useNavigate();

  useEffect(() => {
    setUnauthorizedHandler(() => {
      navigate('/login', { replace: true });
    });
    return () => {
      setUnauthorizedHandler(null);
    };
  }, [navigate]);

  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RequireAuth>
            <AppHeader />
          </RequireAuth>
        }
      >
        <Route path="/workspaces" element={<WorkspaceList />} />
        <Route path="/workspaces/:workspaceId/board" element={<Board />} />
        <Route path="/stories/:storyId" element={<StoryDetail />} />
      </Route>
      <Route path="/" element={<Navigate to="/workspaces" replace />} />
      <Route path="*" element={<Navigate to="/workspaces" replace />} />
    </Routes>
  );
}

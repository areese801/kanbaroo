import { useState, type FormEvent, type JSX } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCreateWorkspace, useWorkspaces } from '../queries/workspaces';

type FormState = {
  key: string;
  name: string;
  description: string;
};

const EMPTY_FORM: FormState = { key: '', name: '', description: '' };

export default function WorkspaceList(): JSX.Element {
  const navigate = useNavigate();
  const workspacesQuery = useWorkspaces();
  const createWorkspace = useCreateWorkspace();
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setFormError(null);
    const key = form.key.trim();
    const name = form.name.trim();
    const description = form.description.trim();
    if (!key || !name) {
      setFormError('Key and name are required.');
      return;
    }
    try {
      await createWorkspace.mutateAsync({
        key,
        name,
        description: description ? description : null,
      });
      setForm(EMPTY_FORM);
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : 'Could not create workspace.';
      setFormError(message);
    }
  }

  const isSubmitting = createWorkspace.isPending;

  return (
    <section className="page">
      <header className="page-header">
        <h1>Workspaces</h1>
        <p className="muted">Pick a workspace to open its board, or create a new one.</p>
      </header>

      <div className="workspace-list">
        {workspacesQuery.isLoading ? (
          <p className="muted">Loading workspaces...</p>
        ) : null}

        {workspacesQuery.isError ? (
          <div className="error-panel" role="alert">
            <p className="error-text">Could not load workspaces.</p>
            <button type="button" onClick={() => workspacesQuery.refetch()}>
              Retry
            </button>
          </div>
        ) : null}

        {workspacesQuery.isSuccess && workspacesQuery.data.items.length === 0 ? (
          <p className="muted">
            No workspaces yet. Create one below, or run <code>kb workspace create</code> from the
            CLI.
          </p>
        ) : null}

        {workspacesQuery.isSuccess && workspacesQuery.data.items.length > 0 ? (
          <ul className="workspace-rows">
            {workspacesQuery.data.items.map((workspace) => (
              <li key={workspace.id}>
                <button
                  type="button"
                  className="workspace-row"
                  onClick={() => navigate(`/workspaces/${workspace.id}/board`)}
                >
                  <span className="workspace-row-name">{workspace.name}</span>
                  <span className="workspace-row-key">{workspace.key}</span>
                  {workspace.description ? (
                    <span className="workspace-row-description">{workspace.description}</span>
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      <section className="workspace-create">
        <h2>Create workspace</h2>
        <form onSubmit={handleSubmit} noValidate>
          <div className="form-row">
            <label htmlFor="workspace-key">Key</label>
            <input
              id="workspace-key"
              name="key"
              value={form.key}
              spellCheck={false}
              autoComplete="off"
              placeholder="KAN"
              onChange={(event) => setForm((s) => ({ ...s, key: event.target.value }))}
            />
          </div>
          <div className="form-row">
            <label htmlFor="workspace-name">Name</label>
            <input
              id="workspace-name"
              name="name"
              value={form.name}
              autoComplete="off"
              placeholder="Kanbaroo"
              onChange={(event) => setForm((s) => ({ ...s, name: event.target.value }))}
            />
          </div>
          <div className="form-row">
            <label htmlFor="workspace-description">Description (optional)</label>
            <input
              id="workspace-description"
              name="description"
              value={form.description}
              autoComplete="off"
              placeholder="What is this workspace for?"
              onChange={(event) => setForm((s) => ({ ...s, description: event.target.value }))}
            />
          </div>
          {formError !== null ? (
            <p role="alert" className="error-text">
              {formError}
            </p>
          ) : null}
          <button type="submit" disabled={isSubmitting}>
            {isSubmitting ? 'Creating...' : 'Create workspace'}
          </button>
        </form>
      </section>
    </section>
  );
}

import { useMemo, type JSX } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useWorkspace } from '../queries/workspaces';
import { useEpicsByWorkspace } from '../queries/epics';
import { useStoriesByWorkspace } from '../queries/stories';
import { useEventStream } from '../hooks/useEventStream';
import type { Epic, Story } from '../types/api';

export type EpicStoryCounts = {
  total: number;
  open: number;
};

const EMPTY_COUNTS: EpicStoryCounts = { total: 0, open: 0 };

/**
 * Group a workspace's stories by epic id and count the total and the
 * still-open ones per epic. "Open" means any state other than `done`.
 * Stories without an epic are ignored. The caller is responsible for
 * passing a list that already excludes soft-deleted rows (the list
 * endpoint does this by default).
 */
export function countStoriesByEpic(stories: Story[]): Map<string, EpicStoryCounts> {
  const counts = new Map<string, EpicStoryCounts>();
  for (const story of stories) {
    if (story.epic_id === null) {
      continue;
    }
    const current = counts.get(story.epic_id) ?? { total: 0, open: 0 };
    current.total += 1;
    if (story.state !== 'done') {
      current.open += 1;
    }
    counts.set(story.epic_id, current);
  }
  return counts;
}

type EpicRowProps = {
  epic: Epic;
  counts: EpicStoryCounts;
  countsReady: boolean;
};

function EpicRow({ epic, counts, countsReady }: EpicRowProps): JSX.Element {
  return (
    <tr data-epic-id={epic.id}>
      <td className="epic-table-key">{epic.human_id}</td>
      <td className="epic-table-title">{epic.title}</td>
      <td>
        <span className={`epic-state epic-state-${epic.state}`}>{epic.state}</span>
      </td>
      <td className="epic-table-count">{countsReady ? counts.total : '?'}</td>
      <td className="epic-table-count">{countsReady ? counts.open : '?'}</td>
      <td className="epic-table-updated">{epic.updated_at}</td>
    </tr>
  );
}

export default function EpicList(): JSX.Element {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const workspaceQuery = useWorkspace(workspaceId);
  const epicsQuery = useEpicsByWorkspace(workspaceId);
  const storiesQuery = useStoriesByWorkspace(workspaceId);
  useEventStream(workspaceId ?? null);

  const countsByEpic = useMemo(
    () => countStoriesByEpic(storiesQuery.data ?? []),
    [storiesQuery.data],
  );
  const countsReady = storiesQuery.isSuccess;
  const epics = epicsQuery.data ?? [];
  const boardPath = `/workspaces/${encodeURIComponent(workspaceId ?? '')}/board`;

  return (
    <section className="page epic-list">
      <header className="page-header epic-list-header">
        <div>
          <h1>
            Epics
            {workspaceQuery.data ? (
              <span className="board-header-key"> ({workspaceQuery.data.key})</span>
            ) : null}
          </h1>
          <p className="muted">
            Story counts include every non-deleted story in the epic. Open counts exclude
            stories in Done.
          </p>
        </div>
        <div className="board-header-actions">
          <Link to={boardPath} className="button-link secondary">
            Board
          </Link>
        </div>
      </header>

      {epicsQuery.isLoading ? <p className="muted">Loading epics...</p> : null}

      {epicsQuery.isError ? (
        <div className="error-panel" role="alert">
          <p className="error-text">Could not load epics.</p>
          <button type="button" onClick={() => epicsQuery.refetch()}>
            Retry
          </button>
        </div>
      ) : null}

      {storiesQuery.isError ? (
        <div className="error-panel" role="alert">
          <p className="error-text">Could not load stories, so counts are unavailable.</p>
          <button type="button" onClick={() => storiesQuery.refetch()}>
            Retry
          </button>
        </div>
      ) : null}

      {epicsQuery.isSuccess && epics.length === 0 ? (
        <p className="muted">
          No epics yet. Create one with <code>kb epic create</code> from the CLI.
        </p>
      ) : null}

      {epicsQuery.isSuccess && epics.length > 0 ? (
        <table className="epic-table">
          <thead>
            <tr>
              <th scope="col">Key</th>
              <th scope="col">Title</th>
              <th scope="col">State</th>
              <th scope="col">Stories</th>
              <th scope="col">Open</th>
              <th scope="col">Last updated</th>
            </tr>
          </thead>
          <tbody>
            {epics.map((epic) => (
              <EpicRow
                key={epic.id}
                epic={epic}
                counts={countsByEpic.get(epic.id) ?? EMPTY_COUNTS}
                countsReady={countsReady}
              />
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}

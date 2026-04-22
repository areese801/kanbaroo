import type { JSX } from 'react';
import { useParams } from 'react-router-dom';
import { useWorkspace } from '../queries/workspaces';
import { useStoriesByWorkspace } from '../queries/stories';
import { useWorkspaceTags } from '../queries/tags';
import {
  ACTOR_LABELS,
  PRIORITY_LABELS,
  STATE_LABELS,
  STORY_STATES,
  type ActorType,
  type Story,
  type StoryPriority,
  type StoryState,
} from '../types/api';

const TITLE_TRUNCATE_AT = 80;

const ACTOR_DOT_COLOR: Record<ActorType, string> = {
  human: '#7faa3a',
  claude: '#a569ff',
  system: '#888',
};

function truncateTitle(title: string): string {
  if (title.length <= TITLE_TRUNCATE_AT) {
    return title;
  }
  return `${title.slice(0, TITLE_TRUNCATE_AT - 1)}\u2026`;
}

function priorityChipClass(priority: StoryPriority): string {
  return `priority-chip priority-${priority}`;
}

function StoryCard({ story }: { story: Story }): JSX.Element {
  return (
    <article className="story-card" aria-disabled="true" style={{ cursor: 'default' }}>
      <div className="story-card-top">
        <span className="story-human-id">{story.human_id}</span>
        {story.priority !== 'none' ? (
          <span className={priorityChipClass(story.priority)}>
            {PRIORITY_LABELS[story.priority]}
          </span>
        ) : null}
      </div>
      <div className="story-card-title">{truncateTitle(story.title)}</div>
      {story.state_actor_type !== null ? (
        <div className="story-card-actor">
          <span
            className="actor-dot"
            aria-hidden="true"
            style={{ backgroundColor: ACTOR_DOT_COLOR[story.state_actor_type] }}
          />
          <span className="actor-label">{ACTOR_LABELS[story.state_actor_type]}</span>
        </div>
      ) : null}
    </article>
  );
}

type ColumnProps = {
  state: StoryState;
  stories: Story[];
  isBacklogEmptyHint: boolean;
  loadingHint: boolean;
};

function Column({ state, stories, isBacklogEmptyHint, loadingHint }: ColumnProps): JSX.Element {
  const label = STATE_LABELS[state];
  return (
    <section className="board-column" aria-label={label}>
      <header className="board-column-header">
        <span className="board-column-title">{label}</span>
        <span className="board-column-count">({stories.length})</span>
      </header>
      <div className="board-column-body">
        {loadingHint ? <p className="muted small">Loading stories...</p> : null}
        {!loadingHint && stories.length === 0 && isBacklogEmptyHint ? (
          <p className="muted small">
            No stories yet. Create one with <code>kb story create</code> in the CLI.
          </p>
        ) : null}
        {stories.map((story) => (
          <StoryCard key={story.id} story={story} />
        ))}
      </div>
    </section>
  );
}

export default function Board(): JSX.Element {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const workspaceQuery = useWorkspace(workspaceId);
  const storiesQuery = useStoriesByWorkspace(workspaceId);
  // Warm the tag cache for later milestones. The value is not consumed here
  // because story-to-tag joins are deferred to a later milestone.
  useWorkspaceTags(workspaceId);

  const loading = storiesQuery.isLoading;
  const isError = storiesQuery.isError;
  const stories = storiesQuery.data ?? [];
  const boardIsEmpty = !loading && !isError && stories.length === 0;

  const byState: Record<StoryState, Story[]> = {
    backlog: [],
    todo: [],
    in_progress: [],
    in_review: [],
    done: [],
  };
  for (const story of stories) {
    byState[story.state].push(story);
  }

  return (
    <section className="board">
      <header className="board-header">
        <h1>
          {workspaceQuery.data ? workspaceQuery.data.name : 'Board'}
          {workspaceQuery.data ? (
            <span className="board-header-key"> ({workspaceQuery.data.key})</span>
          ) : null}
        </h1>
      </header>

      {isError ? (
        <div className="error-panel" role="alert">
          <p className="error-text">Could not load stories.</p>
          <button type="button" onClick={() => storiesQuery.refetch()}>
            Retry
          </button>
        </div>
      ) : null}

      <div className="board-columns">
        {STORY_STATES.map((state) => (
          <Column
            key={state}
            state={state}
            stories={byState[state]}
            loadingHint={loading}
            isBacklogEmptyHint={state === 'backlog' && boardIsEmpty}
          />
        ))}
      </div>
    </section>
  );
}

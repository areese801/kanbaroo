import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type JSX,
} from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core';
import { useWorkspace } from '../queries/workspaces';
import { useStoriesByWorkspace, useTransitionStory } from '../queries/stories';
import { useWorkspaceTags } from '../queries/tags';
import { useEventStream, type EventStreamState } from '../hooks/useEventStream';
import { useHotkey } from '../hooks/useHotkey';
import { isLegalTransition, resolveDrop } from '../lib/stateMachine';
import StoryCreateModal from '../components/StoryCreateModal';
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
const ILLEGAL_DROP_BANNER_MS = 4000;
const PERSISTENT_FAILURE_THRESHOLD = 3;

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

function StoryCardContent({ story }: { story: Story }): JSX.Element {
  return (
    <>
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
    </>
  );
}

function storyAriaLabel(story: Story): string {
  const priority =
    story.priority === 'none' ? 'no priority' : `${PRIORITY_LABELS[story.priority]} priority`;
  return `${story.human_id} ${story.title}, ${STATE_LABELS[story.state]}, ${priority}`;
}

type DraggableStoryCardProps = {
  story: Story;
  isDragging: boolean;
  onOpen: (storyId: string) => void;
};

function DraggableStoryCard({
  story,
  isDragging,
  onOpen,
}: DraggableStoryCardProps): JSX.Element {
  const { attributes, listeners, setNodeRef, transform } = useDraggable({
    id: `story-${story.id}`,
    data: { storyId: story.id, fromState: story.state, version: story.version },
  });
  const style: CSSProperties = {
    transform: transform ? `translate3d(${transform.x}px, ${transform.y}px, 0)` : undefined,
    opacity: isDragging ? 0.4 : 1,
    cursor: 'grab',
    touchAction: 'none',
  };
  return (
    <article
      ref={setNodeRef}
      className="story-card"
      style={style}
      data-story-id={story.id}
      onClick={() => onOpen(story.id)}
      {...listeners}
      {...attributes}
      aria-label={storyAriaLabel(story)}
      aria-roledescription="draggable story"
    >
      <StoryCardContent story={story} />
    </article>
  );
}

type ColumnProps = {
  state: StoryState;
  stories: Story[];
  totalInState: number;
  isBacklogEmptyHint: boolean;
  loadingHint: boolean;
  activeFromState: StoryState | null;
  draggingStoryId: string | null;
  onOpenStory: (storyId: string) => void;
  onCreateStory: () => void;
  searchActive: boolean;
};

function Column({
  state,
  stories,
  totalInState,
  isBacklogEmptyHint,
  loadingHint,
  activeFromState,
  draggingStoryId,
  onOpenStory,
  onCreateStory,
  searchActive,
}: ColumnProps): JSX.Element {
  const label = STATE_LABELS[state];
  const { setNodeRef, isOver } = useDroppable({ id: `column-${state}` });
  const dropTarget =
    activeFromState === null
      ? 'none'
      : isLegalTransition(activeFromState, state)
        ? 'legal'
        : 'illegal';
  const style: CSSProperties = {};
  if (dropTarget === 'legal') {
    style.borderColor = isOver ? '#7faa3a' : 'rgba(127, 170, 58, 0.45)';
  } else if (dropTarget === 'illegal') {
    style.opacity = 0.5;
  }
  const ariaLabel = `${label}, ${totalInState} ${totalInState === 1 ? 'story' : 'stories'}`;
  const hiddenCount = totalInState - stories.length;
  return (
    <section
      ref={setNodeRef}
      className="board-column"
      aria-label={ariaLabel}
      data-drop-target={dropTarget}
      style={style}
    >
      <header className="board-column-header">
        <span className="board-column-title">{label}</span>
      </header>
      <div className="board-column-body">
        {loadingHint ? <p className="muted small">Loading stories...</p> : null}
        {!loadingHint && stories.length === 0 && searchActive ? (
          <p className="muted small">No matches in {label}.</p>
        ) : null}
        {!loadingHint &&
        stories.length === 0 &&
        !searchActive &&
        isBacklogEmptyHint ? (
          <p className="muted small">
            No stories yet. Press{' '}
            <button
              type="button"
              className="inline-link"
              onClick={onCreateStory}
            >
              + New story
            </button>{' '}
            to create one.
          </p>
        ) : null}
        {stories.map((story) => (
          <DraggableStoryCard
            key={story.id}
            story={story}
            isDragging={draggingStoryId === story.id}
            onOpen={onOpenStory}
          />
        ))}
        {searchActive && hiddenCount > 0 ? (
          <p className="muted small">
            {hiddenCount} hidden by search.
          </p>
        ) : null}
      </div>
    </section>
  );
}

type LiveStatus = 'connected' | 'reconnecting' | 'disconnected';

function liveStatusFrom(stream: EventStreamState): LiveStatus {
  if (stream.status === 'open') {
    return 'connected';
  }
  if (stream.status === 'disconnected' || stream.reconnectAttempts > PERSISTENT_FAILURE_THRESHOLD) {
    return 'disconnected';
  }
  return 'reconnecting';
}

const LIVE_STATUS_COLOR: Record<LiveStatus, string> = {
  connected: '#7faa3a',
  reconnecting: '#e0a050',
  disconnected: '#d66464',
};

const LIVE_STATUS_LABEL: Record<LiveStatus, string> = {
  connected: 'Live updates connected',
  reconnecting: 'Reconnecting...',
  disconnected: 'Live updates disconnected',
};

function LiveIndicator({ status }: { status: LiveStatus }): JSX.Element {
  const label = LIVE_STATUS_LABEL[status];
  return (
    <span className="live-indicator" role="status" aria-label={label} title={label}>
      <span
        className="live-indicator-dot"
        aria-hidden="true"
        style={{ backgroundColor: LIVE_STATUS_COLOR[status] }}
      />
      <span className="live-indicator-text">{label}</span>
    </span>
  );
}

type BannerKind = 'illegal' | 'conflict' | 'invalid' | 'generic';

type Banner = {
  kind: BannerKind;
  message: string;
};

function matchesSearch(story: Story, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) {
    return true;
  }
  if (story.human_id.toLowerCase().startsWith(q)) {
    return true;
  }
  if (story.title.toLowerCase().includes(q)) {
    return true;
  }
  return false;
}

export default function Board(): JSX.Element {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const navigate = useNavigate();
  const workspaceQuery = useWorkspace(workspaceId);
  const storiesQuery = useStoriesByWorkspace(workspaceId);
  useWorkspaceTags(workspaceId);

  const handleOpenStory = (storyId: string): void => {
    navigate(`/stories/${encodeURIComponent(storyId)}`);
  };

  const eventStream = useEventStream(workspaceId ?? null);
  const liveStatus = liveStatusFrom(eventStream);

  const transitionMutation = useTransitionStory(workspaceId ?? '');

  const [activeCard, setActiveCard] = useState<{
    storyId: string;
    fromState: StoryState;
    version: number;
  } | null>(null);
  const [illegalBanner, setIllegalBanner] = useState<string | null>(null);
  const illegalTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [searchVisible, setSearchVisible] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    return () => {
      if (illegalTimerRef.current !== null) {
        clearTimeout(illegalTimerRef.current);
        illegalTimerRef.current = null;
      }
    };
  }, []);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

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
  const byStateTotals: Record<StoryState, number> = {
    backlog: 0,
    todo: 0,
    in_progress: 0,
    in_review: 0,
    done: 0,
  };
  const activeQuery = searchQuery.trim();
  for (const story of stories) {
    byStateTotals[story.state] += 1;
    if (matchesSearch(story, activeQuery)) {
      byState[story.state].push(story);
    }
  }

  const activeStory = useMemo(() => {
    if (!activeCard) {
      return null;
    }
    return stories.find((s) => s.id === activeCard.storyId) ?? null;
  }, [stories, activeCard]);

  const handleDragStart = (event: DragStartEvent): void => {
    const data = event.active.data.current as
      | { storyId: string; fromState: StoryState; version: number }
      | undefined;
    if (!data) {
      return;
    }
    setActiveCard({ storyId: data.storyId, fromState: data.fromState, version: data.version });
  };

  const handleDragCancel = (): void => {
    setActiveCard(null);
  };

  const showIllegalBanner = (from: StoryState, to: StoryState): void => {
    const message = `Cannot move a ${STATE_LABELS[from]} story to ${STATE_LABELS[to]}.`;
    setIllegalBanner(message);
    if (illegalTimerRef.current !== null) {
      clearTimeout(illegalTimerRef.current);
    }
    illegalTimerRef.current = setTimeout(() => {
      setIllegalBanner(null);
      illegalTimerRef.current = null;
    }, ILLEGAL_DROP_BANNER_MS);
  };

  const handleDragEnd = (event: DragEndEvent): void => {
    const dragged = activeCard;
    setActiveCard(null);
    const overId = event.over ? String(event.over.id) : null;
    const resolution = resolveDrop(dragged, overId);
    if (resolution.kind === 'illegal') {
      showIllegalBanner(resolution.fromState, resolution.toState);
      return;
    }
    if (resolution.kind === 'legal') {
      transitionMutation.mutate({
        storyId: resolution.storyId,
        expectedVersion: resolution.expectedVersion,
        toState: resolution.toState,
      });
    }
  };

  const mutationError = transitionMutation.error;
  const mutationBanner: Banner | null = useMemo(() => {
    if (!mutationError) {
      return null;
    }
    const status = mutationError.status;
    if (status === 412) {
      return {
        kind: 'conflict',
        message: 'Someone else changed this story. Refreshed to the latest.',
      };
    }
    if (status === 422) {
      return { kind: 'invalid', message: 'That move is not allowed by the workflow.' };
    }
    const suffix = typeof status === 'number' ? String(status) : 'unknown error';
    return { kind: 'generic', message: `Could not move the story (${suffix}).` };
  }, [mutationError]);

  const openCreate = useCallback(() => {
    setCreateOpen(true);
  }, []);
  const closeCreate = useCallback(() => {
    setCreateOpen(false);
  }, []);

  const revealSearch = useCallback(() => {
    setSearchVisible(true);
    // Defer focus so the input has been rendered.
    queueMicrotask(() => {
      const input = searchInputRef.current;
      if (input) {
        input.focus();
        if (input.value) {
          input.select();
        }
      }
    });
  }, []);

  const clearSearch = useCallback(() => {
    setSearchQuery('');
    setSearchVisible(false);
    const input = searchInputRef.current;
    if (input) {
      input.blur();
    }
  }, []);

  useHotkey('n', (event) => {
    if (createOpen) {
      return;
    }
    event.preventDefault();
    openCreate();
  });

  useHotkey('/', (event) => {
    event.preventDefault();
    revealSearch();
  });

  useHotkey(
    'Escape',
    () => {
      if (createOpen) {
        return;
      }
      if (searchVisible || searchQuery) {
        clearSearch();
      }
    },
    { allowInInputs: true },
  );

  const searchActive = activeQuery.length > 0;

  return (
    <section className="board">
      <header className="board-header">
        <h1>
          {workspaceQuery.data ? workspaceQuery.data.name : 'Board'}
          {workspaceQuery.data ? (
            <span className="board-header-key"> ({workspaceQuery.data.key})</span>
          ) : null}
        </h1>
        <div className="board-header-actions">
          {searchVisible ? (
            <div className="board-search" role="search">
              <input
                ref={searchInputRef}
                type="search"
                className="board-search-input"
                placeholder="Search stories"
                value={searchQuery}
                aria-label="Search stories"
                onChange={(event) => setSearchQuery(event.target.value)}
                onBlur={() => {
                  if (!searchQuery) {
                    setSearchVisible(false);
                  }
                }}
              />
              {searchQuery ? (
                <button
                  type="button"
                  className="board-search-clear"
                  aria-label="Clear search"
                  onClick={clearSearch}
                >
                  x
                </button>
              ) : null}
            </div>
          ) : (
            <button
              type="button"
              className="secondary"
              onClick={revealSearch}
              aria-label="Search stories"
            >
              Search
            </button>
          )}
          <button type="button" onClick={openCreate}>
            + New story
          </button>
          <LiveIndicator status={liveStatus} />
        </div>
      </header>

      {illegalBanner !== null ? (
        <div className="board-banner board-banner-illegal" role="status">
          <p>{illegalBanner}</p>
        </div>
      ) : null}

      {mutationBanner !== null ? (
        <div className="board-banner board-banner-error" role="alert">
          <p>{mutationBanner.message}</p>
          <button
            type="button"
            className="secondary"
            onClick={() => transitionMutation.reset()}
          >
            Dismiss
          </button>
        </div>
      ) : null}

      {isError ? (
        <div className="error-panel" role="alert">
          <p className="error-text">Could not load stories.</p>
          <button type="button" onClick={() => storiesQuery.refetch()}>
            Retry
          </button>
        </div>
      ) : null}

      <DndContext
        sensors={sensors}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
        onDragCancel={handleDragCancel}
      >
        <div className="board-columns">
          {STORY_STATES.map((state) => (
            <Column
              key={state}
              state={state}
              stories={byState[state]}
              totalInState={byStateTotals[state]}
              loadingHint={loading}
              isBacklogEmptyHint={state === 'backlog' && boardIsEmpty}
              activeFromState={activeCard?.fromState ?? null}
              draggingStoryId={activeCard?.storyId ?? null}
              onOpenStory={handleOpenStory}
              onCreateStory={openCreate}
              searchActive={searchActive}
            />
          ))}
        </div>
        <DragOverlay>
          {activeStory ? (
            <article className="story-card story-card-overlay">
              <StoryCardContent story={activeStory} />
            </article>
          ) : null}
        </DragOverlay>
      </DndContext>

      {createOpen && workspaceId ? (
        <StoryCreateModal workspaceId={workspaceId} onClose={closeCreate} />
      ) : null}
    </section>
  );
}

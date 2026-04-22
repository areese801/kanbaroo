import { useCallback, useEffect, useState, type FormEvent, type JSX } from 'react';
import { useParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import ReactMarkdown from 'react-markdown';
import rehypeSanitize from 'rehype-sanitize';
import AuditTrail from '../components/AuditTrail';
import CommentComposer from '../components/CommentComposer';
import CommentThread from '../components/CommentThread';
import TagManager from '../components/TagManager';
import { useEventStream } from '../hooks/useEventStream';
import { useHotkey } from '../hooks/useHotkey';
import {
  useCreateComment,
  useDeleteComment,
  useUpdateComment,
  useComments,
} from '../queries/comments';
import { useEpicsByWorkspace } from '../queries/epics';
import { useStory, useUpdateStory, type StoryUpdatePayload } from '../queries/stories';
import type { ApiError } from '../queries/http';
import {
  ACTOR_LABELS,
  PRIORITY_LABELS,
  STATE_LABELS,
  type ActorType,
  type Story,
  type StoryPriority,
} from '../types/api';

const ACTOR_DOT_COLOR: Record<ActorType, string> = {
  human: '#7faa3a',
  claude: '#a569ff',
  system: '#888',
};

const PRIORITY_OPTIONS: StoryPriority[] = ['none', 'low', 'medium', 'high'];

type EditFormState = {
  title: string;
  description: string;
  priority: StoryPriority;
  epic_id: string;
  branch_name: string;
  commit_sha: string;
  pr_url: string;
};

function initialFormState(story: Story): EditFormState {
  return {
    title: story.title,
    description: story.description ?? '',
    priority: story.priority,
    epic_id: story.epic_id ?? '',
    branch_name: story.branch_name ?? '',
    commit_sha: story.commit_sha ?? '',
    pr_url: story.pr_url ?? '',
  };
}

function buildPayload(form: EditFormState, story: Story): StoryUpdatePayload {
  const payload: StoryUpdatePayload = {};
  if (form.title !== story.title) {
    payload.title = form.title;
  }
  const descriptionFromForm = form.description === '' ? null : form.description;
  if (descriptionFromForm !== (story.description ?? null)) {
    payload.description = descriptionFromForm;
  }
  if (form.priority !== story.priority) {
    payload.priority = form.priority;
  }
  const epicFromForm = form.epic_id === '' ? null : form.epic_id;
  if (epicFromForm !== (story.epic_id ?? null)) {
    payload.epic_id = epicFromForm;
  }
  const branchFromForm = form.branch_name === '' ? null : form.branch_name;
  if (branchFromForm !== (story.branch_name ?? null)) {
    payload.branch_name = branchFromForm;
  }
  const shaFromForm = form.commit_sha === '' ? null : form.commit_sha;
  if (shaFromForm !== (story.commit_sha ?? null)) {
    payload.commit_sha = shaFromForm;
  }
  const prFromForm = form.pr_url === '' ? null : form.pr_url;
  if (prFromForm !== (story.pr_url ?? null)) {
    payload.pr_url = prFromForm;
  }
  return payload;
}

function shortSha(sha: string): string {
  return sha.length <= 12 ? sha : sha.slice(0, 12);
}

type DisplayModeProps = {
  story: Story;
  epicLabel: string | null;
  onEdit: () => void;
};

function DisplayMode({ story, epicLabel, onEdit }: DisplayModeProps): JSX.Element {
  return (
    <div className="story-detail-body" data-mode="display">
      <header className="story-detail-header">
        <h1>{story.title}</h1>
        <div className="story-detail-chips">
          <span className="story-human-id">{story.human_id}</span>
          {story.priority !== 'none' ? (
            <span className={`priority-chip priority-${story.priority}`}>
              {PRIORITY_LABELS[story.priority]}
            </span>
          ) : null}
          <span className={`state-chip state-${story.state}`}>
            {STATE_LABELS[story.state]}
          </span>
          {story.state_actor_type !== null ? (
            <span className="story-card-actor">
              <span
                className="actor-dot"
                aria-hidden="true"
                style={{ backgroundColor: ACTOR_DOT_COLOR[story.state_actor_type] }}
              />
              <span className="actor-label">
                {ACTOR_LABELS[story.state_actor_type]}
              </span>
            </span>
          ) : null}
          <button type="button" className="secondary" onClick={onEdit}>
            Edit
          </button>
        </div>
      </header>
      <section className="story-description" aria-label="Description">
        {story.description && story.description.trim() !== '' ? (
          <ReactMarkdown rehypePlugins={[rehypeSanitize]}>
            {story.description}
          </ReactMarkdown>
        ) : (
          <p className="muted">No description.</p>
        )}
      </section>
      <section className="story-metadata" aria-label="Metadata">
        <dl>
          <div>
            <dt>Epic</dt>
            <dd>{epicLabel ?? 'No epic'}</dd>
          </div>
          <div>
            <dt>Branch</dt>
            <dd>{story.branch_name ?? 'None'}</dd>
          </div>
          <div>
            <dt>Commit</dt>
            <dd>
              {story.commit_sha ? (
                <code className="commit-chip">{shortSha(story.commit_sha)}</code>
              ) : (
                'None'
              )}
            </dd>
          </div>
          <div>
            <dt>PR</dt>
            <dd>
              {story.pr_url ? (
                <a href={story.pr_url} target="_blank" rel="noreferrer">
                  {story.pr_url}
                </a>
              ) : (
                'None'
              )}
            </dd>
          </div>
        </dl>
      </section>
    </div>
  );
}

type EditModeProps = {
  story: Story;
  epicOptions: { id: string; label: string }[];
  form: EditFormState;
  onChange: (update: Partial<EditFormState>) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onCancel: () => void;
  busy: boolean;
  errorMessage: string | null;
};

function EditMode({
  story,
  epicOptions,
  form,
  onChange,
  onSubmit,
  onCancel,
  busy,
  errorMessage,
}: EditModeProps): JSX.Element {
  return (
    <form className="story-detail-edit" onSubmit={onSubmit} aria-label="Edit story">
      {errorMessage ? (
        <p className="error-text" role="alert">
          {errorMessage}
        </p>
      ) : null}
      <label>
        <span>Title</span>
        <input
          type="text"
          value={form.title}
          onChange={(event) => onChange({ title: event.target.value })}
          required
          disabled={busy}
        />
      </label>
      <label>
        <span>Description</span>
        <textarea
          rows={8}
          value={form.description}
          onChange={(event) => onChange({ description: event.target.value })}
          disabled={busy}
        />
        <span className="muted small">Markdown supported.</span>
      </label>
      <div className="form-row">
        <label>
          <span>Priority</span>
          <select
            value={form.priority}
            onChange={(event) =>
              onChange({ priority: event.target.value as StoryPriority })
            }
            disabled={busy}
          >
            {PRIORITY_OPTIONS.map((p) => (
              <option key={p} value={p}>
                {PRIORITY_LABELS[p]}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Epic</span>
          <select
            value={form.epic_id}
            onChange={(event) => onChange({ epic_id: event.target.value })}
            disabled={busy}
          >
            <option value="">No epic</option>
            {epicOptions.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label>
        <span>Branch</span>
        <input
          type="text"
          value={form.branch_name}
          onChange={(event) => onChange({ branch_name: event.target.value })}
          disabled={busy}
        />
      </label>
      <label>
        <span>Commit SHA</span>
        <input
          type="text"
          value={form.commit_sha}
          onChange={(event) => onChange({ commit_sha: event.target.value })}
          disabled={busy}
        />
      </label>
      <label>
        <span>PR URL</span>
        <input
          type="url"
          value={form.pr_url}
          onChange={(event) => onChange({ pr_url: event.target.value })}
          disabled={busy}
        />
      </label>
      <div className="form-actions">
        <button
          type="button"
          className="secondary"
          onClick={onCancel}
          disabled={busy}
        >
          Cancel
        </button>
        <button type="submit" disabled={busy}>
          {busy ? `Saving ${story.human_id}...` : 'Save changes'}
        </button>
      </div>
    </form>
  );
}

type ConflictModalProps = {
  onAcknowledge: () => void;
};

function ConflictModal({ onAcknowledge }: ConflictModalProps): JSX.Element {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Conflict">
      <div className="modal">
        <h2>The story changed on the server</h2>
        <p>
          Pulling the latest to avoid overwriting someone else&apos;s changes.
        </p>
        <div className="modal-actions">
          <button type="button" onClick={onAcknowledge}>
            OK
          </button>
        </div>
      </div>
    </div>
  );
}

export default function StoryDetail(): JSX.Element {
  const { storyId } = useParams<{ storyId: string }>();
  const safeStoryId = storyId ?? '';
  const queryClient = useQueryClient();
  const storyQuery = useStory(safeStoryId);
  const story = storyQuery.data ?? null;
  const workspaceId = story?.workspace_id ?? null;

  useEventStream(workspaceId);

  const epicsQuery = useEpicsByWorkspace(workspaceId);
  const commentsQuery = useComments(safeStoryId);

  const updateStory = useUpdateStory(safeStoryId, workspaceId);
  const createComment = useCreateComment(safeStoryId);
  const updateComment = useUpdateComment(safeStoryId);
  const deleteComment = useDeleteComment(safeStoryId);

  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<EditFormState | null>(null);
  const [editBaseVersion, setEditBaseVersion] = useState<number | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [showConflict, setShowConflict] = useState(false);
  const [commentConflictId, setCommentConflictId] = useState<string | null>(null);

  useEffect(() => {
    if (!editing && story) {
      setForm(initialFormState(story));
    }
  }, [story, editing]);

  const handleEnterEdit = useCallback((): void => {
    if (!story || editing) {
      return;
    }
    setForm(initialFormState(story));
    setEditBaseVersion(story.version);
    setSaveError(null);
    setEditing(true);
  }, [story, editing]);

  const handleExitEdit = useCallback((): void => {
    setEditing(false);
    setEditBaseVersion(null);
    setSaveError(null);
  }, []);

  useHotkey('e', handleEnterEdit, { enabled: !editing && !!story });
  useHotkey('Escape', handleExitEdit, {
    enabled: editing && !showConflict,
    allowInInputs: true,
  });

  if (storyQuery.isLoading || !story) {
    return (
      <section className="story-detail" aria-busy="true">
        <p className="muted">Loading story...</p>
      </section>
    );
  }
  if (storyQuery.isError) {
    return (
      <section className="story-detail">
        <div className="error-panel" role="alert">
          <p className="error-text">Could not load story.</p>
          <button type="button" onClick={() => storyQuery.refetch()}>
            Retry
          </button>
        </div>
      </section>
    );
  }

  const epics = epicsQuery.data ?? [];
  const openEpics = epics.filter((e) => e.state === 'open');
  const epicOptions = openEpics.map((epic) => ({
    id: epic.id,
    label: `${epic.human_id} ${epic.title}`,
  }));
  const epicForStory = story.epic_id
    ? epics.find((e) => e.id === story.epic_id) ?? null
    : null;
  const epicLabel = epicForStory
    ? `${epicForStory.human_id} ${epicForStory.title}`
    : null;

  const handleChange = (update: Partial<EditFormState>): void => {
    setForm((prev) => (prev ? { ...prev, ...update } : prev));
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (!form) {
      return;
    }
    const payload = buildPayload(form, story);
    if (Object.keys(payload).length === 0) {
      setEditing(false);
      return;
    }
    setSaveError(null);
    updateStory.mutate(
      { expectedVersion: editBaseVersion ?? story.version, payload },
      {
        onSuccess: () => {
          setEditing(false);
          setEditBaseVersion(null);
        },
        onError: (err: ApiError) => {
          if (err.status === 412) {
            setShowConflict(true);
            queryClient.invalidateQueries({ queryKey: ['story', safeStoryId] });
          } else {
            setSaveError(err.message);
          }
        },
      },
    );
  };

  const handleConflictAck = (): void => {
    setShowConflict(false);
    setEditing(false);
    setEditBaseVersion(null);
    setSaveError(null);
  };

  const handleCreateComment = async (body: string): Promise<void> => {
    await createComment.mutateAsync({ body });
  };

  const handleReply = async (parentId: string, body: string): Promise<void> => {
    await createComment.mutateAsync({ body, parent_id: parentId });
  };

  const handleEditComment = async (
    commentId: string,
    expectedVersion: number,
    body: string,
  ): Promise<void> => {
    try {
      await updateComment.mutateAsync({ commentId, expectedVersion, body });
      setCommentConflictId((prev) => (prev === commentId ? null : prev));
    } catch (err) {
      if (err instanceof Error && (err as ApiError).status === 412) {
        setCommentConflictId(commentId);
        queryClient.invalidateQueries({ queryKey: ['comments', safeStoryId] });
        return;
      }
      throw err;
    }
  };

  const handleDeleteComment = async (
    commentId: string,
    expectedVersion: number,
  ): Promise<void> => {
    try {
      await deleteComment.mutateAsync({ commentId, expectedVersion });
    } catch (err) {
      if (err instanceof Error && (err as ApiError).status === 412) {
        setCommentConflictId(commentId);
        queryClient.invalidateQueries({ queryKey: ['comments', safeStoryId] });
        return;
      }
      throw err;
    }
  };

  const comments = commentsQuery.data ?? [];

  return (
    <section className="story-detail">
      {showConflict ? <ConflictModal onAcknowledge={handleConflictAck} /> : null}
      <div className="story-detail-columns">
        <div className="story-detail-main">
          {editing && form ? (
            <EditMode
              story={story}
              epicOptions={epicOptions}
              form={form}
              onChange={handleChange}
              onSubmit={handleSubmit}
              onCancel={handleExitEdit}
              busy={updateStory.isPending}
              errorMessage={saveError}
            />
          ) : (
            <DisplayMode
              story={story}
              epicLabel={epicLabel}
              onEdit={handleEnterEdit}
            />
          )}
          <section className="story-comments" aria-label="Comments">
            <h2>Comments</h2>
            {commentsQuery.isLoading ? (
              <p className="muted small" aria-busy="true">
                Loading comments...
              </p>
            ) : null}
            {commentsQuery.isError ? (
              <div role="alert">
                <p className="error-text small">Could not load comments.</p>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => commentsQuery.refetch()}
                >
                  Retry
                </button>
              </div>
            ) : null}
            {!commentsQuery.isLoading && !commentsQuery.isError ? (
              <CommentThread
                comments={comments}
                conflictCommentId={commentConflictId}
                onReply={handleReply}
                onEdit={handleEditComment}
                onDelete={handleDeleteComment}
              />
            ) : null}
            <CommentComposer
              submitLabel="Post"
              onSubmit={handleCreateComment}
              busy={createComment.isPending}
            />
          </section>
        </div>
        <aside className="story-detail-sidebar">
          {workspaceId ? (
            <TagManager storyId={safeStoryId} workspaceId={workspaceId} />
          ) : null}
          <AuditTrail storyId={safeStoryId} />
        </aside>
      </div>
    </section>
  );
}

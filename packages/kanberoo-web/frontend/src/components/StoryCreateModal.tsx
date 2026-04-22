import { useEffect, useRef, useState, type FormEvent, type JSX } from 'react';
import { useNavigate } from 'react-router-dom';
import Modal from './Modal';
import { useEpicsByWorkspace } from '../queries/epics';
import { useCreateStory, type CreateStoryPayload } from '../queries/stories';
import { PRIORITY_LABELS, type Story, type StoryPriority } from '../types/api';

const PRIORITY_OPTIONS: StoryPriority[] = ['none', 'low', 'medium', 'high'];

export type StoryCreateModalProps = {
  workspaceId: string;
  onClose: () => void;
  onCreated?: (story: Story) => void;
};

type FormState = {
  title: string;
  description: string;
  priority: StoryPriority;
  epic_id: string;
};

const EMPTY_FORM: FormState = {
  title: '',
  description: '',
  priority: 'none',
  epic_id: '',
};

export default function StoryCreateModal({
  workspaceId,
  onClose,
  onCreated,
}: StoryCreateModalProps): JSX.Element {
  const navigate = useNavigate();
  const titleInputRef = useRef<HTMLInputElement>(null);
  const epicsQuery = useEpicsByWorkspace(workspaceId);
  const createStory = useCreateStory(workspaceId);

  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);

  const openEpics = (epicsQuery.data ?? []).filter((e) => e.state === 'open');

  useEffect(() => {
    setFormError(null);
  }, [form]);

  const handleSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    const trimmedTitle = form.title.trim();
    if (!trimmedTitle) {
      setFormError('Title is required.');
      return;
    }
    const payload: CreateStoryPayload = { title: trimmedTitle };
    const description = form.description.trim();
    if (description) {
      payload.description = description;
    }
    if (form.priority !== 'none') {
      payload.priority = form.priority;
    }
    if (form.epic_id) {
      payload.epic_id = form.epic_id;
    }
    createStory.mutate(payload, {
      onSuccess: (story) => {
        if (onCreated) {
          onCreated(story);
        }
        onClose();
        navigate(`/stories/${encodeURIComponent(story.id)}`);
      },
      onError: (err) => {
        setFormError(err.message);
      },
    });
  };

  const busy = createStory.isPending;

  return (
    <Modal
      labelledBy="story-create-heading"
      onClose={busy ? () => undefined : onClose}
      initialFocusRef={titleInputRef}
    >
      <h2 id="story-create-heading">New story</h2>
      <form className="story-create-form" onSubmit={handleSubmit} noValidate>
        <label>
          <span>Title</span>
          <input
            ref={titleInputRef}
            type="text"
            value={form.title}
            onChange={(event) => setForm((s) => ({ ...s, title: event.target.value }))}
            placeholder="What needs to happen?"
            autoComplete="off"
            disabled={busy}
            required
          />
        </label>
        <label>
          <span>Description</span>
          <textarea
            rows={5}
            value={form.description}
            onChange={(event) =>
              setForm((s) => ({ ...s, description: event.target.value }))
            }
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
                setForm((s) => ({ ...s, priority: event.target.value as StoryPriority }))
              }
              disabled={busy}
            >
              {PRIORITY_OPTIONS.map((priority) => (
                <option key={priority} value={priority}>
                  {PRIORITY_LABELS[priority]}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Epic</span>
            <select
              value={form.epic_id}
              onChange={(event) =>
                setForm((s) => ({ ...s, epic_id: event.target.value }))
              }
              disabled={busy}
            >
              <option value="">No epic</option>
              {openEpics.map((epic) => (
                <option key={epic.id} value={epic.id}>
                  {epic.human_id} {epic.title}
                </option>
              ))}
            </select>
          </label>
        </div>
        {formError !== null ? (
          <p className="error-text" role="alert">
            {formError}
          </p>
        ) : null}
        <div className="modal-actions">
          <button type="button" className="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" disabled={busy}>
            {busy ? 'Creating...' : 'Create story'}
          </button>
        </div>
      </form>
    </Modal>
  );
}

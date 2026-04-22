import { useEffect, useMemo, useRef, useState, type FormEvent, type JSX } from 'react';
import { useCreateTag, useStoryTags, useWorkspaceTags } from '../queries/tags';
import { useAddStoryTags, useRemoveStoryTag } from '../queries/stories';
import type { Tag } from '../types/api';

export type TagManagerProps = {
  storyId: string;
  workspaceId: string;
};

function TagChip({
  tag,
  onRemove,
  busy,
}: {
  tag: Tag;
  onRemove: (tagId: string) => void;
  busy: boolean;
}): JSX.Element {
  const style = tag.color ? { backgroundColor: tag.color } : undefined;
  return (
    <span className="tag-chip" style={style} data-tag-id={tag.id}>
      <span className="tag-chip-name">{tag.name}</span>
      <button
        type="button"
        className="tag-chip-remove"
        aria-label={`Remove tag ${tag.name}`}
        onClick={() => onRemove(tag.id)}
        disabled={busy}
      >
        &times;
      </button>
    </span>
  );
}

type PickerProps = {
  storyTags: Tag[];
  workspaceTags: Tag[];
  onAdd: (tagId: string) => void;
  onCreate: (name: string, color: string | null) => Promise<void>;
  onClose: () => void;
  busy: boolean;
};

function TagPicker({
  storyTags,
  workspaceTags,
  onAdd,
  onCreate,
  onClose,
  busy,
}: PickerProps): JSX.Element {
  const [search, setSearch] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [newColor, setNewColor] = useState('');
  const [createError, setCreateError] = useState<string | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    searchRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent): void {
      if (event.key === 'Escape') {
        onClose();
      }
    }
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  const availableTags = useMemo(() => {
    const attached = new Set(storyTags.map((t) => t.id));
    const needle = search.trim().toLowerCase();
    return workspaceTags
      .filter((t) => !attached.has(t.id))
      .filter((t) => (needle === '' ? true : t.name.toLowerCase().includes(needle)));
  }, [storyTags, workspaceTags, search]);

  const handleCreate = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    const name = newName.trim();
    if (!name) {
      return;
    }
    setCreateError(null);
    try {
      await onCreate(name, newColor.trim() === '' ? null : newColor.trim());
      setNewName('');
      setNewColor('');
      setShowCreate(false);
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : 'Could not create tag.');
    }
  };

  return (
    <div className="tag-picker" role="dialog" aria-label="Add tag">
      <input
        ref={searchRef}
        type="text"
        className="tag-picker-search"
        placeholder="Search tags..."
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        disabled={busy}
      />
      <ul className="tag-picker-list">
        {availableTags.length === 0 ? (
          <li className="muted small">No matching tags.</li>
        ) : (
          availableTags.map((tag) => (
            <li key={tag.id}>
              <button
                type="button"
                className="tag-picker-item"
                onClick={() => onAdd(tag.id)}
                disabled={busy}
              >
                {tag.color ? (
                  <span
                    className="tag-picker-swatch"
                    aria-hidden="true"
                    style={{ backgroundColor: tag.color }}
                  />
                ) : null}
                <span>{tag.name}</span>
              </button>
            </li>
          ))
        )}
      </ul>
      {showCreate ? (
        <form className="tag-picker-create" onSubmit={handleCreate}>
          <label>
            <span className="muted small">Name</span>
            <input
              type="text"
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              required
            />
          </label>
          <label>
            <span className="muted small">Color (optional, e.g. #7faa3a)</span>
            <input
              type="text"
              value={newColor}
              onChange={(event) => setNewColor(event.target.value)}
              placeholder="#7faa3a"
              maxLength={7}
            />
          </label>
          {createError ? (
            <p className="error-text small" role="alert">
              {createError}
            </p>
          ) : null}
          <div className="tag-picker-create-actions">
            <button
              type="button"
              className="secondary"
              onClick={() => {
                setShowCreate(false);
                setCreateError(null);
              }}
              disabled={busy}
            >
              Cancel
            </button>
            <button type="submit" disabled={busy || newName.trim() === ''}>
              Create and add
            </button>
          </div>
        </form>
      ) : (
        <button
          type="button"
          className="tag-picker-create-toggle"
          onClick={() => setShowCreate(true)}
          disabled={busy}
        >
          Create new tag
        </button>
      )}
    </div>
  );
}

export default function TagManager({ storyId, workspaceId }: TagManagerProps): JSX.Element {
  const storyTagsQuery = useStoryTags(storyId);
  const workspaceTagsQuery = useWorkspaceTags(workspaceId);
  const addTags = useAddStoryTags(storyId, workspaceId);
  const removeTag = useRemoveStoryTag(storyId, workspaceId);
  const createTag = useCreateTag(workspaceId);
  const [pickerOpen, setPickerOpen] = useState(false);

  const storyTags = storyTagsQuery.data ?? [];
  const workspaceTags = workspaceTagsQuery.data ?? [];
  const busy =
    addTags.isPending || removeTag.isPending || createTag.isPending;

  const handleRemove = (tagId: string): void => {
    removeTag.mutate({ tagId });
  };

  const handleAdd = (tagId: string): void => {
    addTags.mutate(
      { tag_ids: [tagId] },
      {
        onSuccess: () => setPickerOpen(false),
      },
    );
  };

  const handleCreate = async (name: string, color: string | null): Promise<void> => {
    const tag = await createTag.mutateAsync({ name, color });
    await addTags.mutateAsync({ tag_ids: [tag.id] });
    setPickerOpen(false);
  };

  const mutationError =
    addTags.error ?? removeTag.error ?? null;

  return (
    <section className="tag-manager" aria-label="Tags">
      <header className="tag-manager-header">
        <h3>Tags</h3>
      </header>
      {storyTags.length === 0 ? (
        <p className="muted small">No tags.</p>
      ) : (
        <ul className="tag-chip-row" aria-label="Story tags">
          {storyTags.map((tag) => (
            <li key={tag.id}>
              <TagChip tag={tag} onRemove={handleRemove} busy={busy} />
            </li>
          ))}
        </ul>
      )}
      {mutationError ? (
        <p className="error-text small" role="alert">
          {mutationError.message}
        </p>
      ) : null}
      <div className="tag-manager-add">
        {pickerOpen ? (
          <TagPicker
            storyTags={storyTags}
            workspaceTags={workspaceTags}
            onAdd={handleAdd}
            onCreate={handleCreate}
            onClose={() => setPickerOpen(false)}
            busy={busy}
          />
        ) : (
          <button
            type="button"
            className="secondary"
            onClick={() => setPickerOpen(true)}
          >
            Add tag
          </button>
        )}
      </div>
    </section>
  );
}

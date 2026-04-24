import { useState, type FormEvent, type JSX } from 'react';

export type CommentComposerProps = {
  initialValue?: string;
  submitLabel: string;
  placeholder?: string;
  onSubmit: (body: string) => Promise<void> | void;
  onCancel?: () => void;
  disabled?: boolean;
  busy?: boolean;
};

export default function CommentComposer({
  initialValue = '',
  submitLabel,
  placeholder = 'Write a comment. Markdown supported.',
  onSubmit,
  onCancel,
  disabled = false,
  busy = false,
}: CommentComposerProps): JSX.Element {
  const [value, setValue] = useState(initialValue);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    const trimmed = value.trim();
    if (!trimmed || busy) {
      return;
    }
    await onSubmit(trimmed);
    if (!initialValue) {
      setValue('');
    }
  };

  return (
    <form className="comment-composer" onSubmit={handleSubmit}>
      <textarea
        className="comment-composer-body"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder={placeholder}
        rows={3}
        disabled={disabled || busy}
      />
      <div className="comment-composer-actions">
        {onCancel ? (
          <button
            type="button"
            className="secondary"
            onClick={onCancel}
            disabled={busy}
          >
            Cancel
          </button>
        ) : null}
        <button type="submit" disabled={disabled || busy || value.trim() === ''}>
          {busy ? 'Saving...' : submitLabel}
        </button>
      </div>
    </form>
  );
}

import { useMemo, useState, type JSX } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeSanitize from 'rehype-sanitize';
import { ACTOR_LABELS, type ActorType, type Comment } from '../types/api';
import CommentComposer from './CommentComposer';

const ACTOR_DOT_COLOR: Record<ActorType, string> = {
  human: '#7faa3a',
  claude: '#a569ff',
  system: '#888',
};

export type CommentThreadProps = {
  comments: Comment[];
  conflictCommentId: string | null;
  onReply: (parentId: string, body: string) => Promise<void>;
  onEdit: (commentId: string, expectedVersion: number, body: string) => Promise<void>;
  onDelete: (commentId: string, expectedVersion: number) => Promise<void>;
};

type ThreadNode = {
  comment: Comment;
  replies: Comment[];
};

function buildThread(comments: Comment[]): ThreadNode[] {
  const tops = comments.filter((c) => c.parent_id === null);
  const byParent = new Map<string, Comment[]>();
  for (const c of comments) {
    if (c.parent_id) {
      const list = byParent.get(c.parent_id) ?? [];
      list.push(c);
      byParent.set(c.parent_id, list);
    }
  }
  return tops.map((top) => ({
    comment: top,
    replies: byParent.get(top.id) ?? [],
  }));
}

function CommentBody({ body }: { body: string }): JSX.Element {
  return (
    <div className="comment-body">
      <ReactMarkdown rehypePlugins={[rehypeSanitize]}>{body}</ReactMarkdown>
    </div>
  );
}

type CommentRowProps = {
  comment: Comment;
  canReply: boolean;
  conflict: boolean;
  onReply?: (parentId: string, body: string) => Promise<void>;
  onEdit: (commentId: string, expectedVersion: number, body: string) => Promise<void>;
  onDelete: (commentId: string, expectedVersion: number) => Promise<void>;
};

function CommentRow({
  comment,
  canReply,
  conflict,
  onReply,
  onEdit,
  onDelete,
}: CommentRowProps): JSX.Element {
  const [editing, setEditing] = useState(false);
  const [replying, setReplying] = useState(false);
  const [busy, setBusy] = useState(false);

  const handleEdit = async (body: string): Promise<void> => {
    setBusy(true);
    try {
      await onEdit(comment.id, comment.version, body);
      setEditing(false);
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (): Promise<void> => {
    if (busy) {
      return;
    }
    setBusy(true);
    try {
      await onDelete(comment.id, comment.version);
    } finally {
      setBusy(false);
    }
  };

  const handleReply = async (body: string): Promise<void> => {
    if (!onReply) {
      return;
    }
    setBusy(true);
    try {
      await onReply(comment.id, body);
      setReplying(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className="comment-row" data-comment-id={comment.id}>
      <header className="comment-header">
        <span
          className="actor-dot"
          aria-hidden="true"
          style={{ backgroundColor: ACTOR_DOT_COLOR[comment.actor_type] }}
        />
        <span className="actor-label">{ACTOR_LABELS[comment.actor_type]}</span>
        <span className="comment-timestamp muted small">{comment.created_at}</span>
      </header>
      {editing ? (
        <CommentComposer
          initialValue={comment.body}
          submitLabel="Save"
          onSubmit={handleEdit}
          onCancel={() => setEditing(false)}
          busy={busy}
        />
      ) : (
        <CommentBody body={comment.body} />
      )}
      {conflict ? (
        <p className="comment-conflict small" role="status">
          Someone else changed this comment. Refreshed.
        </p>
      ) : null}
      {!editing ? (
        <div className="comment-actions">
          {canReply && onReply ? (
            <button
              type="button"
              className="link-button"
              onClick={() => setReplying((v) => !v)}
              disabled={busy}
            >
              Reply
            </button>
          ) : null}
          <button
            type="button"
            className="link-button"
            onClick={() => setEditing(true)}
            disabled={busy}
          >
            Edit
          </button>
          <button
            type="button"
            className="link-button danger"
            onClick={handleDelete}
            disabled={busy}
          >
            Delete
          </button>
        </div>
      ) : null}
      {replying && onReply ? (
        <div className="comment-reply">
          <CommentComposer
            submitLabel="Post reply"
            placeholder="Write a reply. Markdown supported."
            onSubmit={handleReply}
            onCancel={() => setReplying(false)}
            busy={busy}
          />
        </div>
      ) : null}
    </article>
  );
}

export default function CommentThread({
  comments,
  conflictCommentId,
  onReply,
  onEdit,
  onDelete,
}: CommentThreadProps): JSX.Element {
  const thread = useMemo(() => buildThread(comments), [comments]);
  if (thread.length === 0) {
    return <p className="muted small">No comments yet.</p>;
  }
  return (
    <div className="comment-thread">
      {thread.map((node) => (
        <div key={node.comment.id} className="comment-node">
          <CommentRow
            comment={node.comment}
            canReply={true}
            conflict={conflictCommentId === node.comment.id}
            onReply={onReply}
            onEdit={onEdit}
            onDelete={onDelete}
          />
          {node.replies.length > 0 ? (
            <div className="comment-replies">
              {node.replies.map((reply) => (
                <CommentRow
                  key={reply.id}
                  comment={reply}
                  canReply={false}
                  conflict={conflictCommentId === reply.id}
                  onEdit={onEdit}
                  onDelete={onDelete}
                />
              ))}
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

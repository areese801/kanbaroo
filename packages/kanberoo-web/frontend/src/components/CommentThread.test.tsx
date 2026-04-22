import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import CommentThread from './CommentThread';
import type { Comment } from '../types/api';

function makeComment(overrides: Partial<Comment>): Comment {
  return {
    id: overrides.id ?? 'c-x',
    story_id: overrides.story_id ?? 'st-1',
    parent_id: overrides.parent_id ?? null,
    body: overrides.body ?? 'body',
    actor_type: overrides.actor_type ?? 'human',
    actor_id: overrides.actor_id ?? 'tok-1',
    created_at: '2026-04-22T00:00:00Z',
    updated_at: '2026-04-22T00:00:00Z',
    deleted_at: null,
    version: overrides.version ?? 1,
  };
}

describe('CommentThread', () => {
  it('renders a flat list nested by parent_id (one level)', () => {
    const comments: Comment[] = [
      makeComment({ id: 'top', body: 'top-level' }),
      makeComment({ id: 'reply', parent_id: 'top', body: 'reply body' }),
      makeComment({ id: 'other', body: 'another top' }),
    ];
    render(
      <CommentThread
        comments={comments}
        conflictCommentId={null}
        onReply={vi.fn()}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    const rows = document.querySelectorAll('[data-comment-id]');
    expect(rows.length).toBe(3);

    const replyRow = document.querySelector('[data-comment-id="reply"]');
    expect(replyRow).not.toBeNull();
    const parentReplies = replyRow?.closest('.comment-replies');
    expect(parentReplies).not.toBeNull();
    expect(screen.getByText('top-level')).toBeInTheDocument();
    expect(screen.getByText('reply body')).toBeInTheDocument();
    expect(screen.getByText('another top')).toBeInTheDocument();
  });

  it('Reply on a top-level comment fires onReply with the right parent id', async () => {
    const onReply = vi.fn(async () => {});
    const comments: Comment[] = [makeComment({ id: 'top', body: 'first' })];
    render(
      <CommentThread
        comments={comments}
        conflictCommentId={null}
        onReply={onReply}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    const user = userEvent.setup();
    const row = document.querySelector('[data-comment-id="top"]') as HTMLElement;
    await user.click(within(row).getByRole('button', { name: 'Reply' }));
    const textareas = row.querySelectorAll('textarea');
    const replyBox = textareas[textareas.length - 1]! as HTMLTextAreaElement;
    await user.type(replyBox, 'a reply');
    await user.click(within(row).getByRole('button', { name: 'Post reply' }));

    expect(onReply).toHaveBeenCalledWith('top', 'a reply');
  });
});

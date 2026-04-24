import { describe, expect, it } from 'vitest';
import {
  ALLOWED_TRANSITIONS,
  isLegalTransition,
  legalTargetsFrom,
  resolveDrop,
} from './stateMachine';
import type { StoryState } from '../types/api';

describe('ALLOWED_TRANSITIONS', () => {
  it('matches the spec section 4.3 state machine exactly', () => {
    expect(ALLOWED_TRANSITIONS.backlog).toEqual(['todo']);
    expect(ALLOWED_TRANSITIONS.todo).toEqual(['in_progress', 'backlog']);
    expect(ALLOWED_TRANSITIONS.in_progress).toEqual(['in_review', 'backlog']);
    expect(ALLOWED_TRANSITIONS.in_review).toEqual(['done', 'in_progress', 'backlog']);
    expect(ALLOWED_TRANSITIONS.done).toEqual(['in_review', 'backlog']);
  });
});

describe('isLegalTransition', () => {
  it('allows backlog -> todo', () => {
    expect(isLegalTransition('backlog', 'todo')).toBe(true);
  });

  it('allows todo -> in_progress and todo -> backlog', () => {
    expect(isLegalTransition('todo', 'in_progress')).toBe(true);
    expect(isLegalTransition('todo', 'backlog')).toBe(true);
  });

  it('allows in_progress -> in_review and in_progress -> backlog', () => {
    expect(isLegalTransition('in_progress', 'in_review')).toBe(true);
    expect(isLegalTransition('in_progress', 'backlog')).toBe(true);
  });

  it('allows in_review -> done, in_review -> in_progress, and in_review -> backlog', () => {
    expect(isLegalTransition('in_review', 'done')).toBe(true);
    expect(isLegalTransition('in_review', 'in_progress')).toBe(true);
    expect(isLegalTransition('in_review', 'backlog')).toBe(true);
  });

  it('allows done -> in_review and done -> backlog', () => {
    expect(isLegalTransition('done', 'in_review')).toBe(true);
    expect(isLegalTransition('done', 'backlog')).toBe(true);
  });

  it('treats same-column as legal (drop zones do not flicker)', () => {
    const states: StoryState[] = ['backlog', 'todo', 'in_progress', 'in_review', 'done'];
    for (const s of states) {
      expect(isLegalTransition(s, s)).toBe(true);
    }
  });

  it('rejects the common illegal moves', () => {
    expect(isLegalTransition('backlog', 'done')).toBe(false);
    expect(isLegalTransition('backlog', 'in_progress')).toBe(false);
    expect(isLegalTransition('backlog', 'in_review')).toBe(false);
    expect(isLegalTransition('todo', 'done')).toBe(false);
    expect(isLegalTransition('todo', 'in_review')).toBe(false);
    expect(isLegalTransition('in_progress', 'done')).toBe(false);
    expect(isLegalTransition('done', 'todo')).toBe(false);
    expect(isLegalTransition('done', 'in_progress')).toBe(false);
  });
});

describe('legalTargetsFrom', () => {
  it('includes the source state itself plus every allowed target', () => {
    const targets = legalTargetsFrom('in_review');
    expect(targets.has('in_review')).toBe(true);
    expect(targets.has('done')).toBe(true);
    expect(targets.has('in_progress')).toBe(true);
    expect(targets.has('backlog')).toBe(true);
    expect(targets.has('todo')).toBe(false);
  });

  it('for backlog only lets the source and todo through', () => {
    const targets = legalTargetsFrom('backlog');
    expect(targets.has('backlog')).toBe(true);
    expect(targets.has('todo')).toBe(true);
    expect(targets.has('in_progress')).toBe(false);
    expect(targets.has('in_review')).toBe(false);
    expect(targets.has('done')).toBe(false);
  });
});

describe('resolveDrop', () => {
  const card = { storyId: 'st-1', fromState: 'todo' as StoryState, version: 5 };

  it('returns noop when nothing is dragged', () => {
    expect(resolveDrop(null, 'column-in_progress')).toEqual({ kind: 'noop' });
  });

  it('returns noop when dropped outside any column', () => {
    expect(resolveDrop(card, null)).toEqual({ kind: 'noop' });
    expect(resolveDrop(card, 'story-other')).toEqual({ kind: 'noop' });
  });

  it('returns noop when dropping onto the source column', () => {
    expect(resolveDrop(card, 'column-todo')).toEqual({ kind: 'noop' });
  });

  it('returns legal with payload for a permitted move', () => {
    expect(resolveDrop(card, 'column-in_progress')).toEqual({
      kind: 'legal',
      storyId: 'st-1',
      expectedVersion: 5,
      toState: 'in_progress',
    });
  });

  it('returns illegal with from/to for a blocked move', () => {
    const backlogCard = { storyId: 'st-2', fromState: 'backlog' as StoryState, version: 1 };
    expect(resolveDrop(backlogCard, 'column-done')).toEqual({
      kind: 'illegal',
      fromState: 'backlog',
      toState: 'done',
    });
  });
});

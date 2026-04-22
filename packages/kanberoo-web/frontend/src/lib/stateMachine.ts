import type { StoryState } from '../types/api';

export const ALLOWED_TRANSITIONS: Readonly<Record<StoryState, readonly StoryState[]>> =
  Object.freeze({
    backlog: Object.freeze(['todo'] as const),
    todo: Object.freeze(['in_progress', 'backlog'] as const),
    in_progress: Object.freeze(['in_review', 'backlog'] as const),
    in_review: Object.freeze(['done', 'in_progress', 'backlog'] as const),
    done: Object.freeze(['in_review', 'backlog'] as const),
  });

export function isLegalTransition(from: StoryState, to: StoryState): boolean {
  if (from === to) {
    return true;
  }
  return ALLOWED_TRANSITIONS[from].includes(to);
}

export function legalTargetsFrom(from: StoryState): ReadonlySet<StoryState> {
  return new Set<StoryState>([from, ...ALLOWED_TRANSITIONS[from]]);
}

export const COLUMN_ID_PREFIX = 'column-';

export type DragResolution =
  | { kind: 'noop' }
  | { kind: 'illegal'; fromState: StoryState; toState: StoryState }
  | { kind: 'legal'; storyId: string; expectedVersion: number; toState: StoryState };

export type DraggedCard = {
  storyId: string;
  fromState: StoryState;
  version: number;
};

export function resolveDrop(
  dragged: DraggedCard | null,
  overId: string | null | undefined,
): DragResolution {
  if (!dragged || !overId || !overId.startsWith(COLUMN_ID_PREFIX)) {
    return { kind: 'noop' };
  }
  const toState = overId.slice(COLUMN_ID_PREFIX.length) as StoryState;
  if (toState === dragged.fromState) {
    return { kind: 'noop' };
  }
  if (!isLegalTransition(dragged.fromState, toState)) {
    return { kind: 'illegal', fromState: dragged.fromState, toState };
  }
  return {
    kind: 'legal',
    storyId: dragged.storyId,
    expectedVersion: dragged.version,
    toState,
  };
}

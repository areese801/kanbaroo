export type StoryState =
  | 'backlog'
  | 'todo'
  | 'in_progress'
  | 'in_review'
  | 'done';

export type StoryPriority = 'none' | 'low' | 'medium' | 'high';

export type ActorType = 'human' | 'claude' | 'system';

export interface Workspace {
  id: string;
  key: string;
  name: string;
  description: string | null;
  next_issue_num: number;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  version: number;
}

export interface Story {
  id: string;
  workspace_id: string;
  epic_id: string | null;
  human_id: string;
  title: string;
  description: string | null;
  priority: StoryPriority;
  state: StoryState;
  state_actor_type: ActorType | null;
  state_actor_id: string | null;
  branch_name: string | null;
  commit_sha: string | null;
  pr_url: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  version: number;
}

export interface Tag {
  id: string;
  workspace_id: string;
  name: string;
  color: string | null;
  created_at: string;
  deleted_at: string | null;
}

export interface Paginated<T> {
  items: T[];
  next_cursor: string | null;
}

export const STORY_STATES: readonly StoryState[] = [
  'backlog',
  'todo',
  'in_progress',
  'in_review',
  'done',
] as const;

export const STATE_LABELS: Record<StoryState, string> = {
  backlog: 'Backlog',
  todo: 'To do',
  in_progress: 'In progress',
  in_review: 'In review',
  done: 'Done',
};

export const PRIORITY_LABELS: Record<StoryPriority, string> = {
  none: 'None',
  low: 'Low',
  medium: 'Medium',
  high: 'High',
};

export const ACTOR_LABELS: Record<ActorType, string> = {
  human: 'Human',
  claude: 'Claude',
  system: 'System',
};

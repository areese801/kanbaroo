import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';
import { apiFetch } from '../api/client';
import { apiRequest, makeApiError, requestJson, type ApiError } from './http';
import type { Paginated, Story, StoryPriority, StoryState } from '../types/api';

export function useStoriesByWorkspace(
  workspaceId: string | null | undefined,
): UseQueryResult<Story[], Error> {
  return useQuery<Story[], Error>({
    queryKey: ['stories', workspaceId],
    queryFn: async () => {
      const path = `/api/v1/workspaces/${encodeURIComponent(
        workspaceId as string,
      )}/stories?limit=200&include_deleted=false`;
      const envelope = await requestJson<Paginated<Story>>(path);
      return envelope.items;
    },
    enabled: Boolean(workspaceId),
  });
}

export function useStory(
  storyId: string | null | undefined,
): UseQueryResult<Story, Error> {
  return useQuery<Story, Error>({
    queryKey: ['story', storyId],
    queryFn: () =>
      requestJson<Story>(`/api/v1/stories/${encodeURIComponent(storyId as string)}`),
    enabled: Boolean(storyId),
  });
}

export type StoryUpdatePayload = {
  title?: string;
  description?: string | null;
  priority?: StoryPriority;
  epic_id?: string | null;
  branch_name?: string | null;
  commit_sha?: string | null;
  pr_url?: string | null;
};

export type UpdateStoryInput = {
  expectedVersion: number;
  payload: StoryUpdatePayload;
};

type UpdateStoryContext = {
  previous: Story | undefined;
};

export function useUpdateStory(
  storyId: string,
  workspaceId: string | null | undefined,
): UseMutationResult<Story, ApiError, UpdateStoryInput, UpdateStoryContext> {
  const queryClient = useQueryClient();
  const storyKey = ['story', storyId] as const;
  return useMutation<Story, ApiError, UpdateStoryInput, UpdateStoryContext>({
    mutationFn: async (input) => {
      const response = await apiFetch(
        `/api/v1/stories/${encodeURIComponent(storyId)}`,
        {
          method: 'PATCH',
          headers: {
            'If-Match': String(input.expectedVersion),
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(input.payload),
        },
      );
      if (!response.ok) {
        let body = '';
        try {
          body = await response.text();
        } catch {
          // ignore
        }
        throw makeApiError(response.status, response.statusText, body);
      }
      return (await response.json()) as Story;
    },
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey: storyKey });
      const previous = queryClient.getQueryData<Story>(storyKey);
      if (previous) {
        queryClient.setQueryData<Story>(storyKey, {
          ...previous,
          ...input.payload,
        } as Story);
      }
      return { previous };
    },
    onError: (_error, _input, context) => {
      if (context?.previous !== undefined) {
        queryClient.setQueryData<Story>(storyKey, context.previous);
      }
    },
    onSuccess: (story) => {
      queryClient.setQueryData<Story>(storyKey, story);
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: storyKey });
      if (workspaceId) {
        queryClient.invalidateQueries({ queryKey: ['stories', workspaceId] });
      }
      queryClient.invalidateQueries({ queryKey: ['audit', 'story', storyId] });
    },
  });
}

export type AddStoryTagsInput = { tag_ids: string[] };

export function useAddStoryTags(
  storyId: string,
  workspaceId: string | null | undefined,
): UseMutationResult<Story, ApiError, AddStoryTagsInput> {
  const queryClient = useQueryClient();
  return useMutation<Story, ApiError, AddStoryTagsInput>({
    mutationFn: async (input) => {
      const response = await apiRequest(
        `/api/v1/stories/${encodeURIComponent(storyId)}/tags`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(input),
        },
      );
      return (await response.json()) as Story;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['story-tags', storyId] });
      queryClient.invalidateQueries({ queryKey: ['story', storyId] });
      queryClient.invalidateQueries({ queryKey: ['audit', 'story', storyId] });
      if (workspaceId) {
        queryClient.invalidateQueries({ queryKey: ['stories', workspaceId] });
      }
    },
  });
}

export type RemoveStoryTagInput = { tagId: string };

export function useRemoveStoryTag(
  storyId: string,
  workspaceId: string | null | undefined,
): UseMutationResult<void, ApiError, RemoveStoryTagInput> {
  const queryClient = useQueryClient();
  return useMutation<void, ApiError, RemoveStoryTagInput>({
    mutationFn: async (input) => {
      await apiRequest(
        `/api/v1/stories/${encodeURIComponent(storyId)}/tags/${encodeURIComponent(
          input.tagId,
        )}`,
        { method: 'DELETE' },
      );
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['story-tags', storyId] });
      queryClient.invalidateQueries({ queryKey: ['story', storyId] });
      queryClient.invalidateQueries({ queryKey: ['audit', 'story', storyId] });
      if (workspaceId) {
        queryClient.invalidateQueries({ queryKey: ['stories', workspaceId] });
      }
    },
  });
}

export type CreateStoryPayload = {
  title: string;
  description?: string | null;
  priority?: StoryPriority;
  epic_id?: string | null;
  branch_name?: string | null;
  commit_sha?: string | null;
  pr_url?: string | null;
};

export function useCreateStory(
  workspaceId: string | null | undefined,
): UseMutationResult<Story, ApiError, CreateStoryPayload> {
  const queryClient = useQueryClient();
  return useMutation<Story, ApiError, CreateStoryPayload>({
    mutationFn: async (payload) => {
      const response = await apiRequest(
        `/api/v1/workspaces/${encodeURIComponent(workspaceId as string)}/stories`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
      );
      return (await response.json()) as Story;
    },
    onSuccess: () => {
      if (workspaceId) {
        queryClient.invalidateQueries({ queryKey: ['stories', workspaceId] });
      }
    },
  });
}

export type TransitionStoryInput = {
  storyId: string;
  expectedVersion: number;
  toState: StoryState;
  reason?: string;
};

export type TransitionStoryError = Error & { status?: number };

type TransitionStoryContext = {
  previous: Story[] | undefined;
};

type ApiErrorBody = {
  error?: {
    message?: string;
    code?: string;
  };
};

const MAX_ERROR_BODY_CHARS = 240;

async function postTransition(input: TransitionStoryInput): Promise<Story> {
  const body: { to_state: StoryState; reason?: string } = { to_state: input.toState };
  if (input.reason !== undefined) {
    body.reason = input.reason;
  }
  const response = await apiFetch(
    `/api/v1/stories/${encodeURIComponent(input.storyId)}/transition`,
    {
      method: 'POST',
      headers: {
        'If-Match': String(input.expectedVersion),
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    },
  );
  if (!response.ok) {
    let message = `API ${response.status}: ${response.statusText || 'request failed'}`;
    try {
      const text = await response.text();
      if (text) {
        try {
          const parsed = JSON.parse(text) as ApiErrorBody;
          if (parsed.error?.message) {
            message = `${message} ${parsed.error.message}`;
          } else if (text.length <= MAX_ERROR_BODY_CHARS) {
            message = `${message} ${text}`;
          }
        } catch {
          if (text.length <= MAX_ERROR_BODY_CHARS) {
            message = `${message} ${text}`;
          }
        }
      }
    } catch {
      // response body was not readable; fall through with the status line
    }
    const error: TransitionStoryError = new Error(message);
    error.status = response.status;
    throw error;
  }
  return (await response.json()) as Story;
}

export function useTransitionStory(
  workspaceId: string,
): UseMutationResult<Story, TransitionStoryError, TransitionStoryInput, TransitionStoryContext> {
  const queryClient = useQueryClient();
  const queryKey = ['stories', workspaceId] as const;
  return useMutation<Story, TransitionStoryError, TransitionStoryInput, TransitionStoryContext>({
    mutationFn: postTransition,
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey });
      const previous = queryClient.getQueryData<Story[]>(queryKey);
      if (previous) {
        const next = previous.map((story) =>
          story.id === input.storyId ? { ...story, state: input.toState } : story,
        );
        queryClient.setQueryData<Story[]>(queryKey, next);
      }
      return { previous };
    },
    onError: (_error, _input, context) => {
      if (context?.previous !== undefined) {
        queryClient.setQueryData<Story[]>(queryKey, context.previous);
      }
    },
    onSuccess: (story) => {
      const current = queryClient.getQueryData<Story[]>(queryKey);
      if (current) {
        const next = current.map((entry) => (entry.id === story.id ? story : entry));
        queryClient.setQueryData<Story[]>(queryKey, next);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey });
    },
  });
}

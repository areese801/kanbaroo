import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';
import { apiFetch } from '../api/client';
import { requestJson } from './http';
import type { Paginated, Story, StoryState } from '../types/api';

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

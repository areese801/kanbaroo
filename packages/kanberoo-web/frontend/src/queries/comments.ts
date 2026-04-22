import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';
import { apiFetch } from '../api/client';
import { apiRequest, makeApiError, requestJson, type ApiError } from './http';
import type { Comment, CommentListResponse } from '../types/api';

export function useComments(
  storyId: string | null | undefined,
): UseQueryResult<Comment[], Error> {
  return useQuery<Comment[], Error>({
    queryKey: ['comments', storyId],
    queryFn: async () => {
      const path = `/api/v1/stories/${encodeURIComponent(
        storyId as string,
      )}/comments?limit=200`;
      const envelope = await requestJson<CommentListResponse>(path);
      return envelope.items;
    },
    enabled: Boolean(storyId),
  });
}

export type CreateCommentInput = {
  body: string;
  parent_id?: string | null;
};

export function useCreateComment(
  storyId: string,
): UseMutationResult<Comment, ApiError, CreateCommentInput> {
  const queryClient = useQueryClient();
  return useMutation<Comment, ApiError, CreateCommentInput>({
    mutationFn: async (input) => {
      const body: { body: string; parent_id?: string } = { body: input.body };
      if (input.parent_id) {
        body.parent_id = input.parent_id;
      }
      const response = await apiRequest(
        `/api/v1/stories/${encodeURIComponent(storyId)}/comments`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
      );
      return (await response.json()) as Comment;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['comments', storyId] });
      queryClient.invalidateQueries({ queryKey: ['audit', 'story', storyId] });
    },
  });
}

export type UpdateCommentInput = {
  commentId: string;
  expectedVersion: number;
  body: string;
};

type UpdateCommentContext = {
  previous: Comment[] | undefined;
};

export function useUpdateComment(
  storyId: string,
): UseMutationResult<Comment, ApiError, UpdateCommentInput, UpdateCommentContext> {
  const queryClient = useQueryClient();
  const listKey = ['comments', storyId] as const;
  return useMutation<Comment, ApiError, UpdateCommentInput, UpdateCommentContext>({
    mutationFn: async (input) => {
      const response = await apiFetch(
        `/api/v1/comments/${encodeURIComponent(input.commentId)}`,
        {
          method: 'PATCH',
          headers: {
            'If-Match': String(input.expectedVersion),
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ body: input.body }),
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
      return (await response.json()) as Comment;
    },
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey: listKey });
      const previous = queryClient.getQueryData<Comment[]>(listKey);
      if (previous) {
        const next = previous.map((c) =>
          c.id === input.commentId ? { ...c, body: input.body } : c,
        );
        queryClient.setQueryData<Comment[]>(listKey, next);
      }
      return { previous };
    },
    onError: (_error, _input, context) => {
      if (context?.previous !== undefined) {
        queryClient.setQueryData<Comment[]>(listKey, context.previous);
      }
    },
    onSuccess: (comment) => {
      const current = queryClient.getQueryData<Comment[]>(listKey);
      if (current) {
        const next = current.map((c) => (c.id === comment.id ? comment : c));
        queryClient.setQueryData<Comment[]>(listKey, next);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: listKey });
      queryClient.invalidateQueries({ queryKey: ['audit', 'story', storyId] });
    },
  });
}

export type DeleteCommentInput = {
  commentId: string;
  expectedVersion: number;
};

type DeleteCommentContext = {
  previous: Comment[] | undefined;
};

export function useDeleteComment(
  storyId: string,
): UseMutationResult<void, ApiError, DeleteCommentInput, DeleteCommentContext> {
  const queryClient = useQueryClient();
  const listKey = ['comments', storyId] as const;
  return useMutation<void, ApiError, DeleteCommentInput, DeleteCommentContext>({
    mutationFn: async (input) => {
      const response = await apiFetch(
        `/api/v1/comments/${encodeURIComponent(input.commentId)}`,
        {
          method: 'DELETE',
          headers: { 'If-Match': String(input.expectedVersion) },
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
    },
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey: listKey });
      const previous = queryClient.getQueryData<Comment[]>(listKey);
      if (previous) {
        const next = previous.filter((c) => c.id !== input.commentId);
        queryClient.setQueryData<Comment[]>(listKey, next);
      }
      return { previous };
    },
    onError: (_error, _input, context) => {
      if (context?.previous !== undefined) {
        queryClient.setQueryData<Comment[]>(listKey, context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: listKey });
      queryClient.invalidateQueries({ queryKey: ['audit', 'story', storyId] });
    },
  });
}

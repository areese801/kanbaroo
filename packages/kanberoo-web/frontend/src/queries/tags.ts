import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';
import { requestJson, type ApiError } from './http';
import type { Tag } from '../types/api';

type TagListEnvelope = { items: Tag[] };

export function useWorkspaceTags(
  workspaceId: string | null | undefined,
): UseQueryResult<Tag[], Error> {
  return useQuery<Tag[], Error>({
    queryKey: ['tags', workspaceId],
    queryFn: async () => {
      const path = `/api/v1/workspaces/${encodeURIComponent(
        workspaceId as string,
      )}/tags`;
      const envelope = await requestJson<TagListEnvelope>(path);
      return envelope.items;
    },
    enabled: Boolean(workspaceId),
  });
}

export function useStoryTags(
  storyId: string | null | undefined,
): UseQueryResult<Tag[], Error> {
  return useQuery<Tag[], Error>({
    queryKey: ['story-tags', storyId],
    queryFn: async () => {
      const path = `/api/v1/stories/${encodeURIComponent(storyId as string)}/tags`;
      const envelope = await requestJson<TagListEnvelope>(path);
      return envelope.items;
    },
    enabled: Boolean(storyId),
  });
}

export type CreateTagInput = {
  name: string;
  color?: string | null;
};

export function useCreateTag(
  workspaceId: string | null | undefined,
): UseMutationResult<Tag, ApiError, CreateTagInput> {
  const queryClient = useQueryClient();
  return useMutation<Tag, ApiError, CreateTagInput>({
    mutationFn: (input) =>
      requestJson<Tag>(
        `/api/v1/workspaces/${encodeURIComponent(workspaceId as string)}/tags`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(input),
        },
      ),
    onSuccess: () => {
      if (workspaceId) {
        queryClient.invalidateQueries({ queryKey: ['tags', workspaceId] });
      }
    },
  });
}

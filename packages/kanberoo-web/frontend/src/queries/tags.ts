import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { requestJson } from './http';
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

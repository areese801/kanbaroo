import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { requestJson } from './http';
import type { Paginated, Story } from '../types/api';

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

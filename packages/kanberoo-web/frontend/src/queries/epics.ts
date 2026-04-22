import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { requestJson } from './http';
import type { Epic, Paginated } from '../types/api';

export function useEpicsByWorkspace(
  workspaceId: string | null | undefined,
): UseQueryResult<Epic[], Error> {
  return useQuery<Epic[], Error>({
    queryKey: ['epics', workspaceId],
    queryFn: async () => {
      const path = `/api/v1/workspaces/${encodeURIComponent(
        workspaceId as string,
      )}/epics?limit=200`;
      const envelope = await requestJson<Paginated<Epic>>(path);
      return envelope.items;
    },
    enabled: Boolean(workspaceId),
  });
}

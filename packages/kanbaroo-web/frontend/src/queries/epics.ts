import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { requestAllPages } from './http';
import type { Epic } from '../types/api';

export function useEpicsByWorkspace(
  workspaceId: string | null | undefined,
): UseQueryResult<Epic[], Error> {
  return useQuery<Epic[], Error>({
    queryKey: ['epics', workspaceId],
    queryFn: () =>
      requestAllPages<Epic>(
        `/api/v1/workspaces/${encodeURIComponent(workspaceId as string)}/epics`,
      ),
    enabled: Boolean(workspaceId),
  });
}

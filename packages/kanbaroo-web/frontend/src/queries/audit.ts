import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { requestJson } from './http';
import type { AuditEvent, Paginated } from '../types/api';

export function useStoryAudit(
  storyId: string | null | undefined,
): UseQueryResult<AuditEvent[], Error> {
  return useQuery<AuditEvent[], Error>({
    queryKey: ['audit', 'story', storyId],
    queryFn: async () => {
      const path = `/api/v1/audit/entity/story/${encodeURIComponent(
        storyId as string,
      )}?limit=200`;
      const envelope = await requestJson<Paginated<AuditEvent>>(path);
      return envelope.items;
    },
    enabled: Boolean(storyId),
  });
}

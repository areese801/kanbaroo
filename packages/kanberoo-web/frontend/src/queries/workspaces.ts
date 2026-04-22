import { useMutation, useQuery, useQueryClient, type UseMutationResult, type UseQueryResult } from '@tanstack/react-query';
import { requestJson } from './http';
import type { Paginated, Workspace } from '../types/api';

export type CreateWorkspacePayload = {
  key: string;
  name: string;
  description?: string | null;
};

export function useWorkspaces(): UseQueryResult<Paginated<Workspace>, Error> {
  return useQuery<Paginated<Workspace>, Error>({
    queryKey: ['workspaces'],
    queryFn: () => requestJson<Paginated<Workspace>>('/api/v1/workspaces?limit=200'),
  });
}

export function useWorkspace(id: string | null | undefined): UseQueryResult<Workspace, Error> {
  return useQuery<Workspace, Error>({
    queryKey: ['workspace', id],
    queryFn: () => requestJson<Workspace>(`/api/v1/workspaces/${encodeURIComponent(id as string)}`),
    enabled: Boolean(id),
  });
}

export function useCreateWorkspace(): UseMutationResult<Workspace, Error, CreateWorkspacePayload> {
  const queryClient = useQueryClient();
  return useMutation<Workspace, Error, CreateWorkspacePayload>({
    mutationFn: (payload) =>
      requestJson<Workspace>('/api/v1/workspaces', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspaces'] });
    },
  });
}

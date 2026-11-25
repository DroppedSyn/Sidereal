// React Query hooks, one per endpoint (plan §10.1).
import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { LOGIN_PATH, apiGet, apiPost } from './client';
import type {
  DayDetail,
  DaySummary,
  Gazette,
  LoginIn,
  Me,
  Run,
  RunStarted,
  SearchResults,
  SourceStatus,
} from './types';

export const DAYS_PAGE = 60;
export const SEARCH_PAGE = 20;

export function useGazette(includeDrop: boolean) {
  return useQuery({
    queryKey: ['gazette', includeDrop],
    queryFn: () => apiGet<Gazette>('/api/gazette', { include_drop: includeDrop || undefined }),
    placeholderData: keepPreviousData,
  });
}

export function useDays() {
  return useInfiniteQuery({
    queryKey: ['days'],
    queryFn: ({ pageParam }) =>
      apiGet<DaySummary[]>('/api/days', { limit: DAYS_PAGE, before: pageParam }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => (last.length < DAYS_PAGE ? undefined : last[last.length - 1]?.day),
  });
}

export function useDay(day: string | undefined, includeDrop: boolean) {
  return useQuery({
    queryKey: ['day', day, includeDrop],
    queryFn: () =>
      apiGet<DayDetail>(`/api/days/${encodeURIComponent(day ?? '')}`, {
        include_drop: includeDrop || undefined,
      }),
    enabled: day !== undefined,
    placeholderData: keepPreviousData,
  });
}

export function useRuns(limit = 50) {
  return useQuery({
    queryKey: ['runs', limit],
    queryFn: () => apiGet<Run[]>('/api/runs', { limit }),
  });
}

export function useLastRun() {
  return useQuery({
    queryKey: ['runs', 1],
    queryFn: () => apiGet<Run[]>('/api/runs', { limit: 1 }),
    select: (runs) => runs[0] ?? null,
    refetchInterval: 60_000,
  });
}

export function useSources() {
  return useQuery({
    queryKey: ['sources'],
    queryFn: () => apiGet<SourceStatus[]>('/api/sources'),
  });
}

export function useStartRun() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<RunStarted>('/api/runs'),
    onSettled: () => client.invalidateQueries({ queryKey: ['runs'] }),
  });
}

export function useMe() {
  return useQuery({
    queryKey: ['me'],
    queryFn: () => apiGet<Me>('/api/auth/me'),
    staleTime: 5 * 60_000,
  });
}

export function useLogin() {
  return useMutation({ mutationFn: (body: LoginIn) => apiPost<Me>(LOGIN_PATH, body) });
}

export function useLogout() {
  return useMutation({ mutationFn: () => apiPost<undefined>('/api/auth/logout') });
}

export function useSearch(q: string) {
  return useInfiniteQuery({
    queryKey: ['search', q],
    queryFn: ({ pageParam }) =>
      apiGet<SearchResults>('/api/search', { q, limit: SEARCH_PAGE, before: pageParam }),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => last.next_before ?? undefined,
    enabled: q.trim() !== '',
  });
}

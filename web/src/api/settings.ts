// Settings (M27): React Query hooks for the effective config, overrides, notification tests,
// focus areas and source configs. Writes go through apiPost/apiPut/apiDelete (`X-Sidereal: 1`).
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiDelete, apiGet, apiPost, apiPut } from './client';
import type {
  FeedTestIn,
  FeedTestOut,
  FocusArea,
  FocusIn,
  NotifyTestOut,
  Overrides,
  SettingsView,
  SourceConfig,
  SourceIn,
} from './types';

const SETTINGS = ['settings'] as const;
const FOCUS = ['settings', 'focus'] as const;
const SOURCES = ['settings', 'sources'] as const;

export function useSettingsView() {
  return useQuery({ queryKey: SETTINGS, queryFn: () => apiGet<SettingsView>('/api/settings') });
}

export function useSaveOverrides() {
  const client = useQueryClient();
  return useMutation({
    // missing sections reset to the file, like the server does
    mutationFn: (body: Partial<Overrides>) => apiPut<SettingsView>('/api/settings/overrides', body),
    onSuccess: (view) => client.setQueryData(SETTINGS, view),
  });
}

export function useNotifyTest() {
  return useMutation({
    mutationFn: (channel: 'email' | 'discord') =>
      apiPost<NotifyTestOut>('/api/settings/notify/test', { channel }),
  });
}

export function useFocusAreas() {
  return useQuery({ queryKey: FOCUS, queryFn: () => apiGet<FocusArea[]>('/api/settings/focus') });
}

/** Create (`isNew`) or edit a focus area; the key is never sent on an edit. */
export function useSaveFocus() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ area, isNew }: { area: FocusIn; isNew: boolean }) => {
      if (isNew) return apiPost<FocusArea>('/api/settings/focus', area);
      const { key, ...fields } = area;
      return apiPut<FocusArea>(`/api/settings/focus/${encodeURIComponent(key)}`, fields);
    },
    onSettled: () => client.invalidateQueries({ queryKey: FOCUS }),
  });
}

export function useDeleteFocus() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (key: string) => apiDelete<void>(`/api/settings/focus/${encodeURIComponent(key)}`),
    onSettled: () => client.invalidateQueries({ queryKey: FOCUS }),
  });
}

export function useSourceConfigs() {
  return useQuery({ queryKey: SOURCES, queryFn: () => apiGet<SourceConfig[]>('/api/settings/sources') });
}

/** Create (`id` null) or edit a source; key and kind are only sent on create. */
export function useSaveSource() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ source, id }: { source: SourceIn; id: number | null }) => {
      if (id === null) return apiPost<SourceConfig>('/api/settings/sources', source);
      const { name, url, enabled, weight, max_items, options } = source;
      return apiPut<SourceConfig>(`/api/settings/sources/${id}`,
        { name, url, enabled, weight, max_items, options });
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: SOURCES });
      void client.invalidateQueries({ queryKey: ['sources'] });
    },
  });
}

export function useDeleteSource() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiDelete<void>(`/api/settings/sources/${id}`),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: SOURCES });
      void client.invalidateQueries({ queryKey: ['sources'] });
    },
  });
}

export function useTestFeed() {
  return useMutation({
    mutationFn: (body: FeedTestIn) => apiPost<FeedTestOut>('/api/settings/sources/test', body),
  });
}

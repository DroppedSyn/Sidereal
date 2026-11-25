// Feedback and mutes (M24): React Query mutations with optimistic updates of the cached Gazette
// and Day views. Writes go through apiPut/apiPost/apiDelete, which send `X-Sidereal: 1`.
import { useMutation, useQuery, useQueryClient, type QueryClient, type QueryKey } from '@tanstack/react-query';
import { apiDelete, apiGet, apiPost, apiPut } from './client';
import type { Bucket, Counts, DayReadOut, Feedback, Mute, MuteIn, Sections, Story, Vote } from './types';

export type FeedbackChange = { vote: Vote } | { read: boolean } | { hidden: boolean };

interface View {
  sections: Sections;
  counts: Counts;
}

const BUCKETS: Bucket[] = ['top', 'relevant', 'side', 'drop'];
const VIEW_KEYS: QueryKey[] = [['gazette'], ['day']];

/** A copy of `view` with `edit` applied to every story it returns true for; an edit returning
 * null removes the story (hidden) and lowers that bucket's count. */
export function editView<T extends View>(view: T, match: (s: Story) => boolean,
  edit: (s: Story) => Story | null): T {
  const sections = { ...view.sections };
  const counts = { ...view.counts };
  for (const b of BUCKETS) {
    const out: Story[] = [];
    for (const s of view.sections[b]) {
      const next = match(s) ? edit(s) : s;
      if (next) out.push(next);
      else counts[b] = Math.max(0, counts[b] - 1);
    }
    sections[b] = out;
  }
  return { ...view, sections, counts };
}

export function applyChange(s: Story, change: FeedbackChange): Story | null {
  if ('hidden' in change) return change.hidden ? null : { ...s, hidden: false };
  return { ...s, ...change };
}

type Snapshot = Array<[QueryKey, unknown]>;

async function patchViews(client: QueryClient, match: (s: Story) => boolean,
  edit: (s: Story) => Story | null): Promise<Snapshot> {
  const snapshot: Snapshot = [];
  for (const queryKey of VIEW_KEYS) {
    await client.cancelQueries({ queryKey });
    snapshot.push(...client.getQueriesData({ queryKey }));
    client.setQueriesData<View>({ queryKey }, (old) => (old ? editView(old, match, edit) : old));
  }
  return snapshot;
}

function restore(client: QueryClient, snapshot: Snapshot | undefined) {
  for (const [key, data] of snapshot ?? []) client.setQueryData(key, data);
}

function feedbackPath(id: number, change: FeedbackChange): string {
  const route = 'vote' in change ? 'vote' : 'read' in change ? 'read' : 'hidden';
  return `/api/stories/${id}/${route}`;
}

export function useStoryFeedback() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, change }: { id: number; change: FeedbackChange }) =>
      apiPut<Feedback>(feedbackPath(id, change), change),
    onMutate: async ({ id, change }) => ({
      snapshot: await patchViews(client, (s) => s.id === id, (s) => applyChange(s, change)),
    }),
    onError: (_err, _vars, ctx) => restore(client, ctx?.snapshot),
    onSettled: (_data, _err, { change }) => {
      void client.invalidateQueries({ queryKey: ['gazette'] });
      void client.invalidateQueries({ queryKey: ['day'] });
      void client.invalidateQueries({ queryKey: ['search'] });
      if ('hidden' in change) void client.invalidateQueries({ queryKey: ['days'] });
    },
  });
}

export function useMarkDayRead(day: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<DayReadOut>(`/api/days/${encodeURIComponent(day)}/read`),
    onMutate: async () => ({
      snapshot: await patchViews(client, (s) => s.day === day && s.bucket !== 'drop',
        (s) => ({ ...s, read: true })),
    }),
    onError: (_err, _vars, ctx) => restore(client, ctx?.snapshot),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ['gazette'] });
      void client.invalidateQueries({ queryKey: ['day'] });
    },
  });
}

export function useMutes() {
  return useQuery({ queryKey: ['mutes'], queryFn: () => apiGet<Mute[]>('/api/mutes') });
}

export function useAddMute() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: MuteIn) => apiPost<Mute>('/api/mutes', body),
    onSuccess: (mute) =>
      client.setQueryData<Mute[]>(['mutes'], (old) =>
        old && !old.some((m) => m.id === mute.id) ? [...old, mute] : old),
    onSettled: () => client.invalidateQueries({ queryKey: ['mutes'] }),
  });
}

export function useRemoveMute() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiDelete<undefined>(`/api/mutes/${id}`),
    onMutate: async (id) => {
      await client.cancelQueries({ queryKey: ['mutes'] });
      const before = client.getQueryData<Mute[]>(['mutes']);
      client.setQueryData<Mute[]>(['mutes'], (old) => old?.filter((m) => m.id !== id));
      return { before };
    },
    onError: (_err, _id, ctx) => client.setQueryData(['mutes'], ctx?.before),
    onSettled: () => client.invalidateQueries({ queryKey: ['mutes'] }),
  });
}

// Typed API client for the backend.
//
// Plain fetch + Promises. At two endpoints the indirection of a query
// library or typed-fetch wrapper costs more than it pays — but the
// `Promise<T>` return types here are the seam any future migration to
// openapi-fetch / TanStack Query would slot into.

import type { Episode, EpisodeDetail } from './types';

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '';

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`);
  if (!res.ok) {
    throw new Error(`GET ${path} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listEpisodes: () => get<{ episodes: Episode[] }>('/api/episodes'),
  getEpisode: (slug: string) => get<EpisodeDetail>(`/api/episodes/${slug}`),
};
